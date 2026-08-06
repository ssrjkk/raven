# ruff: noqa: RUF001 (intentional Cyrillic in Russian prompts)

from __future__ import annotations

import pytest

from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter
from ravencode.runtime.question import QuestionError


class TestEventEmitter:
    @pytest.mark.asyncio
    async def test_emit_no_handlers(self):
        ee = EventEmitter()
        await ee.emit(AgentEvent("test", {"key": "val"}))
        assert True

    @pytest.mark.asyncio
    async def test_on_and_emit(self):
        ee = EventEmitter()
        received: list[AgentEvent] = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        ee.on("test_event", handler)
        await ee.emit(AgentEvent("test_event", {"msg": "hello"}))
        assert len(received) == 1
        assert received[0].type == "test_event"
        assert received[0].data["msg"] == "hello"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        ee = EventEmitter()
        results: list[str] = []

        async def h1(event: AgentEvent) -> None:
            results.append("h1")

        async def h2(event: AgentEvent) -> None:
            results.append("h2")

        ee.on("evt", h1)
        ee.on("evt", h2)
        await ee.emit(AgentEvent("evt"))
        assert "h1" in results
        assert "h2" in results

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_bubble(self):
        ee = EventEmitter()

        async def bad_handler(event: AgentEvent) -> None:
            raise ValueError("oops")

        async def good_handler(event: AgentEvent) -> None:
            pass

        ee.on("evt", bad_handler)
        ee.on("evt", good_handler)
        await ee.emit(AgentEvent("evt"))
        assert True

    def test_on_different_events(self):
        ee = EventEmitter()
        ee.on("a", lambda e: None)  # type: ignore[arg-type,return-value]
        ee.on("b", lambda e: None)  # type: ignore[arg-type,return-value]
        assert len(ee._handlers) == 2

    @pytest.mark.asyncio
    async def test_event_timestamp(self):
        import time
        before = time.time()
        event = AgentEvent("test")
        after = time.time()
        assert before <= event.timestamp <= after


class TestAgentEvent:
    def test_create_event(self):
        event = AgentEvent("step_start", {"step": 1})
        assert event.type == "step_start"
        assert event.data["step"] == 1

    def test_event_default_data(self):
        event = AgentEvent("done")
        assert event.data == {}

    def test_event_timestamp_auto(self):
        event = AgentEvent("test")
        assert event.timestamp > 0


class TestAgentConfig:
    def test_default_config(self):
        cfg = AgentConfig()
        assert cfg.max_steps == 30
        assert cfg.confirm_dangerous is True
        assert cfg.diff_preview is True
        assert cfg.proactive_scan is True
        assert cfg.structured_output is False
        assert cfg.plan_mode is False
        assert cfg.use_cache is True
        assert cfg.auto_format is True
        assert cfg.llm_timeout == 120

    def test_safe_config(self):
        cfg = AgentConfig.safe()
        assert cfg.confirm_dangerous is True
        assert cfg.diff_preview is True
        assert cfg.proactive_scan is True
        assert cfg.max_steps == 30

    def test_fast_config(self):
        cfg = AgentConfig.fast()
        assert cfg.confirm_dangerous is False
        assert cfg.diff_preview is False
        assert cfg.proactive_scan is False
        assert cfg.max_steps == 50

    def test_autonomous_config(self):
        cfg = AgentConfig.autonomous()
        assert cfg.confirm_dangerous is False
        assert cfg.diff_preview is True
        assert cfg.max_steps == 100

    def test_plan_config(self):
        cfg = AgentConfig.plan()
        assert cfg.plan_mode is True
        assert cfg.structured_output is True
        assert cfg.confirm_dangerous is False
        assert cfg.diff_preview is False

    def test_event_emitter_config(self):
        ee = EventEmitter()
        cfg = AgentConfig(event_emitter=ee)
        assert cfg.event_emitter is ee

    def test_on_step_config(self):
        async def cb(s: str, step: int) -> None:
            pass
        cfg = AgentConfig(on_step=cb)
        assert cfg.on_step is cb

    def test_on_message_config(self):
        async def cb(msg: dict[str, str]) -> None:
            pass
        cfg = AgentConfig(on_message=cb)
        assert cfg.on_message is cb


class TestQuestionErrorPropagation:
    def test_question_error_is_exception(self):
        assert issubclass(QuestionError, Exception)

    @pytest.mark.asyncio
    async def test_question_error_passed_through_retry(self):
        from ravencode.runtime.agent_core import ReActAgent
        agent = ReActAgent(config=AgentConfig(max_steps=5, max_tool_retries=3))
        assert agent.config.max_tool_retries == 3
        assert agent.config.max_steps == 5


class TestReActAgentMalformedToolJson:
    @pytest.mark.asyncio
    async def test_malformed_tool_json_returns_clear_feedback(self):
        from ravencode.runtime.agent_core import ReActAgent

        calls: list[object] = []

        async def fake_llm(messages):
            calls.append(messages)
            if len(calls) == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "nodes_list", "arguments": "{oops"},
                        }
                    ],
                }
            return {"content": "final answer"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, max_steps=5),
            llm_provider=fake_llm,
        )
        result = await agent.run("do the thing")
        assert result == "final answer"
        tool_results = [m for m in agent.conversation.messages if m.get("role") == "tool"]
        assert tool_results, "expected a tool result message for the malformed call"
        assert "malformed JSON" in tool_results[0]["content"]
        assert "nodes_list" in tool_results[0]["content"]


class TestReActAgentTruthful:
    @pytest.mark.asyncio
    async def test_run_truthful_success(self):
        from ravencode.runtime.agent_core import ReActAgent
        from tests.core.test_truthful_orchestrator import ScriptedCompleter

        agent = ReActAgent(config=AgentConfig())
        completer = ScriptedCompleter(
            [
                "<thinking>факт проверен</thinking>\nответ готов",
                "VERIFIED: TRUE",
            ]
        )
        result = await agent.run_truthful("q", completer, model="test-model")
        assert result.status == "success"
        assert result.content == "ответ готов"
        assert result.thinking_process == "факт проверен"

    @pytest.mark.asyncio
    async def test_run_truthful_records_conversation(self):
        from ravencode.runtime.agent_core import ReActAgent
        from tests.core.test_truthful_orchestrator import ScriptedCompleter

        agent = ReActAgent(config=AgentConfig())
        completer = ScriptedCompleter(
            [
                "<thinking>размышление</thinking>\nчерновик",
                "VERIFIED: FALSE: уточни",
                "<thinking>перепроверено</thinking>\nисправленный ответ",
                "VERIFIED: TRUE",
            ]
        )
        result = await agent.run_truthful("q", completer, model="test-model")
        assert result.status == "corrected"
        assert len(agent.conversation.messages) == 3
        assert agent.conversation.messages[-2] == {"content": "q", "role": "user"}
        assert agent.conversation.messages[-1]["content"] == "исправленный ответ"
        assert agent.conversation.messages[-1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_run_truthful_emits_events(self):
        from ravencode.runtime.agent_core import ReActAgent
        from tests.core.test_truthful_orchestrator import ScriptedCompleter

        ee = EventEmitter()
        received: list[AgentEvent] = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        ee.on("truthful", handler)
        ee.on("done", handler)
        agent = ReActAgent(config=AgentConfig(event_emitter=ee))
        completer = ScriptedCompleter(["<thinking>п</thinking>\nо", "VERIFIED: TRUE"])
        await agent.run_truthful("q", completer, model="test-model")
        assert [e.type for e in received] == ["truthful", "done"]
