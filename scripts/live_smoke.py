"""Live end-to-end smoke test against a real LLM provider.

Verifies, in order:
  1. Plain completion (provider reachable, auth works).
  2. SSE streaming.
  3. Full ReAct agent loop with real tool execution
     (write file -> read file -> report content).

Usage (no key is ever written to disk):
    set GROQ_API_KEY=gsk_...
    python scripts/live_smoke.py [model]

Without an explicit model it tries openai/gpt-oss-120b first and falls back
to llama-3.3-70b-versatile (free-tier rate limits). Exit code 0 = all stages
passed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run_stages(provider: Any, model: str) -> list[str]:
    failures: list[str] = []

    # 1) plain completion -----------------------------------------------------
    try:
        resp = await provider.complete(
            [{"role": "user", "content": "Reply with exactly: OK"}], model
        )
        print(f"[1/3] completion: {resp.content[:80]!r} tokens={resp.total_tokens}")
        if "OK" not in resp.content:
            failures.append(f"unexpected completion content: {resp.content[:200]!r}")
    except Exception as exc:
        failures.append(f"completion failed: {exc}")
        print(f"[1/3] FAIL: {exc}")

    # 2) streaming ------------------------------------------------------------
    try:
        chunks = 0
        sample = ""
        async for tok in provider.complete_stream(
            [{"role": "user", "content": "Count from 1 to 5, digits only."}], model
        ):
            chunks += 1
            sample += tok
        print(f"[2/3] streaming: {chunks} chunks, sample={sample[:60]!r}")
        if chunks == 0:
            failures.append("stream produced no chunks")
    except Exception as exc:
        failures.append(f"streaming failed: {exc}")
        print(f"[2/3] FAIL: {exc}")

    # 3) agent end-to-end with real tools -------------------------------------
    try:
        from ravencode.runtime.agent_core import AgentConfig, ReActAgent
        from ravencode.runtime.context import Conversation
        from ravencode.runtime.tools import get_tool_definitions
        from ravencode.runtime.workspace import set_workspace_root

        # Full tool schema (~30 tools) can exceed free-tier TPM limits; the
        # smoke only needs a small read/write loop.
        keep = {"write", "read", "bash"}
        tool_defs = [d for d in get_tool_definitions() if d["function"]["name"] in keep]

        async def adapter(messages: list[dict[str, Any]]) -> dict[str, Any]:
            r = await provider.complete(messages, model, tools=tool_defs)
            out: dict[str, Any] = {"content": r.content or ""}
            if r.tool_calls:
                out["tool_calls"] = [tc.to_dict() for tc in r.tool_calls]
            return out

        with tempfile.TemporaryDirectory() as td:
            set_workspace_root(td)
            try:
                agent = ReActAgent(
                    config=AgentConfig(
                        proactive_scan=False,
                        diff_preview=False,
                        confirm_dangerous=False,
                        max_steps=8,
                        use_cache=False,
                    ),
                    conversation=Conversation(
                        system_prompt=(
                            "You are a precise coding agent. Complete the task using the "
                            "available tools, then answer briefly."
                        )
                    ),
                    llm_provider=adapter,
                )
                result = await agent.run(
                    "Create a file named hello.txt containing exactly: live smoke ok. "
                    "Then read it back and report its exact content."
                )
                print(f"[3/3] agent finished: {result[:200]!r}")
                if result.startswith("[error"):
                    failures.append(f"agent loop errored: {result[:300]}")
                    return failures
                f = Path(td) / "hello.txt"
                if not f.exists():
                    failures.append("agent did not create hello.txt")
                elif "live smoke ok" not in f.read_text(encoding="utf-8"):
                    failures.append("hello.txt has wrong content: " + f.read_text(encoding="utf-8")[:100])
                else:
                    print("[3/3] tool execution verified: hello.txt created and read back")
            finally:
                set_workspace_root(None)
    except Exception as exc:
        failures.append(f"agent loop failed: {exc}")
        print(f"[3/3] FAIL: {exc}")

    return failures


async def main() -> int:
    if not os.environ.get("GROQ_API_KEY"):
        print("FAIL: GROQ_API_KEY is not set")
        return 1

    if len(sys.argv) > 1:
        models = [sys.argv[1]]
    else:
        models = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]

    from raven.core.llm.providers.groq import GroqProvider

    provider = GroqProvider()
    print(f"Provider ready. models={models}")
    try:
        for model in models:
            print(f"\n=== trying model: {model} ===")
            failures = await _run_stages(provider, model)
            if not failures:
                print("\nLIVE SMOKE PASSED (completion + streaming + agent tool loop)")
                return 0
            rate_limited = any("429" in f for f in failures)
            if rate_limited and model is not models[-1]:
                print(f"rate limited on {model}, falling back to next model...")
                continue
            break
    finally:
        await provider.cleanup()

    print("\nLIVE SMOKE FAILED:")
    for f in failures:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
