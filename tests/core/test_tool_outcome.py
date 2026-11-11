"""One vocabulary for what a tool answered, and every surface that has to read it.

Measured before the fix, against the real ``Agent``: a handler answering
``{"error": "GitHub token not configured. Set GITHUB_TOKEN in .env"}`` -- the exact value
``raven/tools/github.py`` returns for every unauthenticated call -- printed ``[github.list -> ok]``.
The agent flattened the value into ``{"result": str(result)[:4000]}`` and then looked for an
``error`` key on the flattened envelope, so nothing a handler reported about its own failure could
reach the progress line, the tool text the model keeps, the orchestrator's error counter, or whether
a task step passed. Policy denials inside the executors were already reported correctly; only what
the handler itself answered was flattened.
"""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from raven.core.agent.agent import Agent, AgentConfig
from raven.core.agents.orchestrator import (
    _CRITIC_PROMPT,
    _NEXT_AGENT_PROMPT,
    _PLAN_PROMPT,
    AgentOrchestrator,
    StatusEmitter,
)
from raven.core.config import settings
from raven.core.llm import LLMResponse, ToolCall
from raven.core.models import PluginTool, Session
from raven.core.security.tool_policy import ToolPolicyEvaluator
from raven.core.task_engine.models import Task, TaskStatus, TaskStep
from raven.core.task_engine.runner import TaskRunner
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.core.tool_outcome import failure_detail
from raven.tools.github import github_list_repos
from raven.tools.shell import shell_command

ROOT = Path(__file__).resolve().parents[2]


class FakeLLM:
    """The planner/critic/router prompts are answered by shape, the rest comes from `responses`."""

    def __init__(
        self,
        plan_steps: list[str] | None = None,
        responses: Sequence[LLMResponse] = (),
        handoff: str = "done",
        critic: str = "ACCEPT",
    ) -> None:
        self._plan = plan_steps or []
        self._responses: Iterator[LLMResponse] = iter(responses)
        self._handoff = handoff
        self._critic = critic

    async def complete(
        self, messages: list[dict[str, Any]], tools: Any = None, model: str | None = None
    ) -> LLMResponse:
        system = messages[0]["content"] if messages else ""
        if system == _PLAN_PROMPT:
            return LLMResponse(content=json.dumps(self._plan))
        if system == _CRITIC_PROMPT:
            return LLMResponse(content=self._critic)
        if system == _NEXT_AGENT_PROMPT:
            return LLMResponse(content=self._handoff)
        return next(self._responses)


class TestVocabulary:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            ({"error": "GitHub token not configured"}, "GitHub token not configured"),
            ({"error": ""}, None),
            ({"error": None, "success": False}, "the tool reported success=False"),
            ({"result": [1, 2]}, None),
            ({"ok": True}, None),
            ("[denied] command 'rm' not in allowlist", "[denied] command 'rm' not in allowlist"),
            ("[error] MCP server 'pool' not connected", "[error] MCP server 'pool' not connected"),
            ("[timeout after 30s]", "[timeout after 30s]"),
            ("traceback\n[exit code: 1]", "command exited with code 1"),
            ("traceback\n[exit code: 127]", "command exited with code 127"),
            ("traceback\n[exit code: -1]", "command exited with code -1"),
            ("nothing wrong here", None),
            ("a grep hit for [exit code: 9] inside the text", None),
            (42, None),
        ],
    )
    def test_the_answer_is_classified_from_the_marker_the_tools_actually_write(
        self, answer: object, expected: str | None
    ) -> None:
        assert failure_detail(answer) == expected

    def test_every_marker_the_classifier_reads_is_still_written_by_a_tool(self) -> None:
        # A marker nobody emits is a classifier reading a string that cannot arrive; one that is
        # emitted but missing from the classifier is a false success waiting for its first run.
        source = "\n".join(
            (ROOT / rel).read_text(encoding="utf-8")
            for rel in ("raven/tools/shell.py", "raven/core/plugin_loader.py", "raven/core/_pyrunner.py")
        )
        for marker in ("[denied]", "[error]", "[timeout", "[exit code:"):
            assert marker in source, f"{marker} is classified but no longer written"


class TestRealEmitters:
    async def test_a_command_outside_the_allowlist_is_not_a_success(self) -> None:
        answer = await shell_command("raven_no_such_command --version")
        assert answer.startswith("[denied]")
        assert failure_detail(answer) == answer

    async def test_a_failing_command_is_not_a_success(self) -> None:
        if sys.platform == "win32":
            answer = await shell_command("where raven-no-such-file-8e1f2a")
        else:
            answer = await shell_command("ls /raven-no-such-file-8e1f2a")
        assert failure_detail(answer) is not None
        assert "exited with code" in str(failure_detail(answer))

    async def test_an_unauthenticated_github_call_is_not_a_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "github_token", SecretStr(""))
        answer = await github_list_repos()
        assert failure_detail(answer) == "GitHub token not configured. Set GITHUB_TOKEN in .env"


class TestAgentProgressLine:
    def _agent(
        self, handler: Callable[..., Any], name: str = "any.tool", arguments: dict[str, Any] | None = None
    ) -> Agent:
        async def wrapped(**kwargs: Any) -> Any:
            answer = handler(**kwargs)
            return await answer if inspect.isawaitable(answer) else answer

        tools = [
            PluginTool(name=name, description="t", parameters={"type": "object", "properties": {}}, handler=wrapped)
        ]
        llm = AsyncMock()
        llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="c1", name=name, arguments=arguments or {})],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="done", finish_reason="stop"),
            ]
        )
        db = AsyncMock()
        db.get_session_messages = AsyncMock(return_value=[])
        db.save_message = AsyncMock(return_value=None)
        return Agent(
            session=Session(id="s", channel="telegram", user_id="u"),
            tools=tools,
            db=db,
            llm=llm,
            config=AgentConfig(max_tool_rounds=3, use_memory=False),
            tool_policy=ToolPolicyEvaluator(profile="full"),
        )

    async def _stream(self, agent: Agent) -> tuple[list[str], list[dict[str, Any]]]:
        """The progress lines the operator saw, and the tool messages the model was given."""
        tokens = [t async for t in agent.run("go")]
        lines = [t for t in tokens if t.startswith("[") and "→" in t]
        llm: Any = agent.llm
        rounds = [list(call.args[0]) for call in llm.complete.await_args_list]
        payloads = [json.loads(m["content"]) for round_ in rounds for m in round_ if m.get("role") == "tool"]
        return lines, payloads

    async def test_a_handler_that_reports_an_error_is_not_printed_as_ok(self) -> None:
        agent = self._agent(lambda **_: {"error": "GitHub token not configured"})
        lines, payloads = await self._stream(agent)
        assert len(lines) == 1
        assert "error: GitHub token not configured" in lines[0]
        assert "→ ok" not in lines[0]
        assert payloads[0]["error"] == "GitHub token not configured"

    async def test_a_refused_command_is_not_printed_as_ok(self) -> None:
        agent = self._agent(shell_command, arguments={"command": "raven_no_such_command --version"})
        lines, payloads = await self._stream(agent)
        assert "→ ok" not in lines[0], lines[0]
        assert payloads[0]["error"].startswith("[denied]")

    async def test_a_success_still_prints_ok(self) -> None:
        agent = self._agent(lambda **_: "pong")
        lines, payloads = await self._stream(agent)
        assert "→ ok" in lines[0], lines[0]
        assert "error" not in payloads[0]
        assert payloads[0]["result"] == "pong"

    async def test_an_output_longer_than_the_cap_keeps_its_status(self) -> None:
        flood = "x" * 6000 + "\n[exit code: 1]"
        agent = self._agent(lambda **_: flood)
        lines, payloads = await self._stream(agent)
        assert "command exited with code 1" in lines[0], lines[0]
        assert len(payloads[0]["result"]) == 4000, "the stored text stays capped; only the status moved"

    async def test_a_failure_reaches_the_model_as_well_as_the_operator(self) -> None:
        agent = self._agent(lambda **_: "boom\n[exit code: 3]")
        _, payloads = await self._stream(agent)
        assert payloads[0]["error"] == "command exited with code 3"
        assert "exit code: 3" in payloads[0]["result"]


class TestEveryConsumerReadsTheSameVocabulary:
    """The three surfaces that decide whether a tool call worked, from one classifier."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "raven/core/agent/agent.py",
            "raven/core/agents/orchestrator.py",
            "raven/core/task_engine/runner.py",
        ],
    )
    def test_each_surface_imports_the_shared_classifier(self, rel_path: str) -> None:
        assert "failure_detail" in (ROOT / rel_path).read_text(encoding="utf-8")

    async def test_the_task_engine_fails_a_step_whose_tool_was_refused(self, tmp_path: Path) -> None:
        attempts = {"n": 0}

        async def refused() -> str:
            attempts["n"] += 1
            return "[denied] command 'rm' not in allowlist"

        registry = ToolRegistry()
        registry.register(ToolSpec(name="cleanup", description="c", parameters={}, handler=refused))
        store = TaskStore(str(tmp_path / "tasks.db"))
        try:
            task = Task(goal="perm", steps=[TaskStep(task_id="", order=0, description="x", tool="cleanup", params={})])
            for step in task.steps:
                step.task_id = task.id
            runner = TaskRunner(store, registry)
            await runner.submit(task)
            done = await runner.wait(task.id, timeout=10)
        finally:
            await store.close()
        assert done is not None
        assert done.status is TaskStatus.FAILED, "a refused command is not a passed step"
        assert attempts["n"] == 1, "a refusal is permanent, so it must not be retried"

    async def test_the_orchestrator_status_stream_reports_the_failure(self) -> None:
        events: list[dict[str, Any]] = []

        async def send(data: str) -> None:
            events.append(json.loads(data))

        async def refused(text: str) -> str:
            return "[denied] command 'nope' not in allowlist"

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="echo",
                description="echo",
                parameters={"text": {"type": "string", "required": True}},
                handler=refused,
            )
        )
        llm = FakeLLM(
            plan_steps=["S1"],
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "hi"})]),
                LLMResponse(content="done"),
            ],
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        await orch.execute("do the thing", profile_override="coder", status_emitter=StatusEmitter(send))
        details = [e["detail"] for e in events if e["event"] == "tool_result"]
        assert details == ["echo: error"], "this stream is what /verbose prints back to the chat"
