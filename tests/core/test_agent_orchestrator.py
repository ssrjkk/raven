from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest

from raven.core.agents.orchestrator import (
    _CRITIC_PROMPT,
    _NEXT_AGENT_PROMPT,
    _PLAN_PROMPT,
    AgentOrchestrator,
    StatusEmitter,
)
from raven.core.llm import LLMResponse, ToolCall
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


class FakeLLM:
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

    async def complete(self, messages: list[dict[str, Any]], tools: Any = None, model: str | None = None) -> LLMResponse:
        system = messages[0]["content"] if messages else ""
        if system == _PLAN_PROMPT:
            return LLMResponse(content=json.dumps(self._plan))
        if system == _CRITIC_PROMPT:
            return LLMResponse(content=self._critic)
        if system == _NEXT_AGENT_PROMPT:
            return LLMResponse(content=self._handoff)
        return next(self._responses)


def make_registry(handlers: dict[str, tuple[dict[str, Any], Callable[..., Any]]]) -> ToolRegistry:
    registry = ToolRegistry()
    for name, (parameters, handler) in handlers.items():
        registry.register(ToolSpec(name=name, description=name, parameters=parameters, handler=handler, category="test"))
    return registry


class TestPlannerExecutorCritic:
    @pytest.mark.asyncio
    async def test_full_flow_success(self):
        calls: list[str] = []

        def echo(text: str) -> str:
            calls.append(text)
            return f"echo:{text}"

        registry = make_registry({"echo": ({"text": {"type": "string", "required": True}}, echo)})
        llm = FakeLLM(
            plan_steps=["Step A", "Step B"],
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "hi"})]),
                LLMResponse(content="The task is done."),
            ],
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")

        assert result.success is True
        assert result.profile == "coder"
        assert result.iterations == 2
        assert calls == ["hi"]
        assert result.content == "The task is done."

    @pytest.mark.asyncio
    async def test_empty_final_response_is_error_not_plan_hint(self):
        registry = make_registry({"echo": ({"text": {"type": "string"}}, lambda text: "ok")})
        llm = FakeLLM(
            plan_steps=["Step A", "Step B"],
            responses=[LLMResponse(content="", finish_reason="stop")],
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")

        assert result.status == "error"
        assert "Step A" not in result.content
        assert "Execution plan" not in result.content
        assert result.content == "[error: task failed]"

    @pytest.mark.asyncio
    async def test_plan_steps_are_recorded_in_context(self):
        calls: list[str] = []

        def echo(text: str) -> str:
            calls.append(text)
            return "ok"

        registry = make_registry({"echo": ({"text": {"type": "string", "required": True}}, echo)})
        llm = FakeLLM(
            plan_steps=["Explore", "Implement", "Test"],
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "x"})]),
                LLMResponse(content="final"),
            ],
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")
        assert result.success is True
        assert calls == ["x"]

    @pytest.mark.asyncio
    async def test_invalid_arguments_never_invoke_handler(self):
        calls: list[str] = []

        def write(path: str) -> str:
            calls.append(path)
            return "written"

        registry = make_registry({"write": ({"path": {"type": "string", "required": True}}, write)})
        llm = FakeLLM(
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="write", arguments={})]),
                LLMResponse(content="done"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")

        assert result.success is True
        assert calls == []

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_without_call(self):
        registry = make_registry({"echo": ({"text": {"type": "string"}}, lambda text: "ok")})
        llm = FakeLLM(
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="ghost_tool", arguments={})]),
                LLMResponse(content="done"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_context_permissions_allowlist_denies_other_tools(self):
        calls: list[str] = []

        def boom() -> str:
            calls.append("boom")
            return "boom"

        registry = make_registry(
            {
                "boom": ({}, boom),
                "echo": ({"text": {"type": "string", "required": True}}, lambda text: "ok"),
            }
        )
        llm = FakeLLM(
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="boom", arguments={})]),
                LLMResponse(content="done"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute(
            "implement the login feature",
            context={"permissions": ["echo"]},
            profile_override="coder",
        )
        assert result.success is True
        assert calls == []

    @pytest.mark.asyncio
    async def test_path_outside_workspace_blocked(self, tmp_path):
        calls: list[str] = []

        def write(path: str) -> str:
            calls.append(path)
            return "written"

        registry = make_registry({"write": ({"path": {"type": "string", "required": True}}, write)})
        llm = FakeLLM(
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="write", arguments={"path": "../escape.txt"})]),
                LLMResponse(content="done"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute(
            "implement the login feature",
            context={"workspace": str(tmp_path)},
            profile_override="coder",
        )
        assert result.success is True
        assert calls == []

    @pytest.mark.asyncio
    async def test_path_inside_workspace_allowed(self, tmp_path):
        calls: list[str] = []
        inside = tmp_path / "a.txt"

        def write(path: str) -> str:
            calls.append(path)
            return "written"

        registry = make_registry({"write": ({"path": {"type": "string", "required": True}}, write)})
        llm = FakeLLM(
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="write", arguments={"path": str(inside)})]),
                LLMResponse(content="done"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute(
            "implement the login feature",
            context={"workspace": str(tmp_path)},
            profile_override="coder",
        )
        assert result.success is True
        assert calls == [str(inside)]

    @pytest.mark.asyncio
    async def test_parallel_tool_calls_in_one_round(self):
        import asyncio

        order: list[str] = []

        async def slow(text: str) -> str:
            order.append(f"s:{text}")
            await asyncio.sleep(0.05)
            order.append(f"e:{text}")
            return f"ok:{text}"

        registry = make_registry({"slow": ({"text": {"type": "string", "required": True}}, slow)})
        llm = FakeLLM(
            responses=[
                LLMResponse(
                    tool_calls=[
                        ToolCall(id="1", name="slow", arguments={"text": "a"}),
                        ToolCall(id="2", name="slow", arguments={"text": "b"}),
                        ToolCall(id="3", name="slow", arguments={"text": "c"}),
                    ]
                ),
                LLMResponse(content="done"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("go", profile_override="coder")

        assert result.success is True
        assert sorted(order) == sorted(["s:a", "s:b", "s:c", "e:a", "e:b", "e:c"])
        prefixes = [x[0] for x in order]
        assert prefixes == ["s", "s", "s", "e", "e", "e"]

    @pytest.mark.asyncio
    async def test_max_iterations_returns_max_steps(self):
        registry = make_registry({"echo": ({"text": {"type": "string", "required": True}}, lambda text: "echo")})
        responses = [LLMResponse(tool_calls=[ToolCall(id=str(i), name="echo", arguments={"text": "x"})]) for i in range(20)]
        llm = FakeLLM(responses=responses)
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=4)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")

        assert result.status == "max_steps"
        assert result.iterations == 4

    @pytest.mark.asyncio
    async def test_handoff_to_another_profile(self):
        registry = make_registry({"echo": ({"text": {"type": "string"}}, lambda text: "ok")})
        llm = FakeLLM(
            responses=[
                LLMResponse(content="needs review next"),
                LLMResponse(content="final done"),
            ],
            handoff="reviewer",
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        result = await orch.execute("implement the login feature", profile_override="coder")

        assert result.handoffs == 1
        assert result.profile == "reviewer"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_status_emitter_reports_events(self):
        events: list[dict[str, Any]] = []

        async def send(data: str) -> None:
            events.append(json.loads(data))

        registry = make_registry({"echo": ({"text": {"type": "string", "required": True}}, lambda text: "echo")})
        llm = FakeLLM(
            plan_steps=["S1"],
            responses=[
                LLMResponse(tool_calls=[ToolCall(id="1", name="echo", arguments={"text": "hi"})]),
                LLMResponse(content="done"),
            ],
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        emitter = StatusEmitter(send)
        await orch.execute("implement the login feature", profile_override="coder", status_emitter=emitter)

        event_types = {e["event"] for e in events}
        assert {"agent_started", "plan_created", "tool_call", "tool_result"}.issubset(event_types)


class TestExecuteWithStream:
    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self):
        registry = make_registry({"echo": ({"text": {"type": "string"}}, lambda text: "ok")})
        llm = FakeLLM(
            responses=[
                LLMResponse(content="streamed answer"),
            ]
        )
        orch = AgentOrchestrator(llm=llm, tool_registry=registry, max_total_iterations=10)  # type: ignore[arg-type]
        chunks = [chunk async for chunk in orch.execute_with_stream("implement the login feature", profile_override="coder")]
        assert "".join(chunks) == "streamed answer"


class TestParsePlanSteps:
    def test_parse_json_array(self):
        from raven.core.agents.orchestrator import _parse_plan_steps

        assert _parse_plan_steps('["a", "b"]') == ["a", "b"]

    def test_parse_fenced_json(self):
        from raven.core.agents.orchestrator import _parse_plan_steps

        assert _parse_plan_steps('```json\n["a", "b"]\n```') == ["a", "b"]

    def test_parse_extracts_array_from_text(self):
        from raven.core.agents.orchestrator import _parse_plan_steps

        assert _parse_plan_steps('Here: ["a", "b"] thanks') == ["a", "b"]

    def test_parse_non_list_returns_empty(self):
        from raven.core.agents.orchestrator import _parse_plan_steps

        assert _parse_plan_steps('"not a list"') == []

    def test_parse_garbage_returns_empty(self):
        from raven.core.agents.orchestrator import _parse_plan_steps

        assert _parse_plan_steps("no brackets here") == []

    def test_parse_filters_non_strings_and_truncates(self):
        from raven.core.agents.orchestrator import _parse_plan_steps

        steps = _parse_plan_steps(json.dumps(["a", 42, "", "b", "c", "d", "e", "f", "g", "h", "i"]))
        assert steps == ["a", "b", "c", "d", "e", "f", "g", "h"]
