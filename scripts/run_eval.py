"""Live task-eval runner: measures real agent success rate end-to-end.

Runs the verifiable task suite (tests/eval/tasks.py) through a real ReActAgent
against a live provider. Ground truth is the resulting workspace state, so the
score is objective. Usage (no key is ever written to disk):

    set GROQ_API_KEY=gsk_...
    python scripts/run_eval.py [--limit N] [--task NAME] [--model MODEL]

Falls back from openai/gpt-oss-120b to llama-3.3-70b-versatile on 429s.
Exit code 0 = all attempted tasks passed their verifiers.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.eval.harness import EvalCase, EvalRunner
from tests.eval.tasks import TASKS, TaskSpec


def _to_case(spec: TaskSpec) -> EvalCase:
    return EvalCase(
        name=spec.name,
        prompt=spec.prompt,
        verifier=spec.verify,
        category="task",
    )


def _keep_tool(name: str) -> bool:
    from ravencode.runtime.tools import MODULE_TOOLS

    if name not in MODULE_TOOLS:
        return False
    # task suite only needs core file/edit/search tools; a smaller schema
    # keeps free-tier prompt sizes manageable
    return name in {"write", "read", "edit", "bash", "glob", "grep", "list_files", "ls"}


def _agent_fn_factory(provider: Any, model: str):
    from ravencode.runtime.agent_core import AgentConfig, ReActAgent
    from ravencode.runtime.context import Conversation
    from ravencode.runtime.tools import get_tool_definitions
    from ravencode.runtime.workspace import set_workspace_root

    tool_defs = [d for d in get_tool_definitions() if _keep_tool(d["function"]["name"])]

    def make(workspace: Path):
        async def agent_fn(prompt: str) -> str:
            async def adapter(messages: list[dict[str, Any]]) -> dict[str, Any]:
                r = await provider.complete(messages, model, tools=tool_defs)
                out: dict[str, Any] = {"content": r.content or ""}
                if r.tool_calls:
                    out["tool_calls"] = [tc.to_dict() for tc in r.tool_calls]
                return out

            set_workspace_root(workspace)
            agent = ReActAgent(
                config=AgentConfig(
                    proactive_scan=False,
                    diff_preview=False,
                    confirm_dangerous=False,
                    max_steps=15,
                    use_cache=False,
                ),
                conversation=Conversation(
                    system_prompt=(
                        "You are a precise coding agent working inside a small workspace. "
                        "Complete the task using the available tools, then answer briefly."
                    )
                ),
                llm_provider=adapter,
            )
            return await agent.run(prompt)

        return agent_fn

    return make


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="run only the first N tasks")
    parser.add_argument("--task", action="append", default=[], help="run a specific task by name")
    parser.add_argument("--model", default=None, help="override model (default: auto with fallback)")
    args = parser.parse_args()

    if not os.environ.get("GROQ_API_KEY"):
        print("FAIL: GROQ_API_KEY is not set")
        return 1

    specs = [t for t in TASKS if not args.task or t.name in args.task]
    if args.limit:
        specs = specs[: args.limit]
    if not specs:
        print("FAIL: no tasks selected")
        return 1

    from raven.core.llm.providers.groq import GroqProvider

    provider = GroqProvider()
    models = [args.model] if args.model else ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]
    runner = EvalRunner(output_dir="eval_results")
    try:
        for model in models:
            print(f"=== model: {model} ({len(specs)} tasks) ===")
            make_agent = _agent_fn_factory(provider, model)
            rate_limited = False
            for spec in specs:
                case = _to_case(spec)
                with tempfile.TemporaryDirectory() as td:
                    workspace = Path(td)
                    spec.setup(workspace)
                    print(f"[run] {spec.name}: {spec.prompt[:60]}...")
                    try:
                        result = await runner.run_case(case, make_agent(workspace), workspace=workspace)
                    except Exception as exc:
                        print(f"[run] {spec.name}: crashed: {exc}")
                        continue
                    status = "PASS" if result.passed else "FAIL"
                    print(f"[run] {spec.name}: {status} score={result.score:.2f} {result.errors}")
                    if any("429" in e for e in result.errors):
                        rate_limited = True
            if not rate_limited:
                break
            print("rate limited; trying next model...")
    finally:
        await provider.cleanup()

    summary = runner.summary()
    report = runner.save_report()
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"report: {report}")
    return 0 if summary.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
