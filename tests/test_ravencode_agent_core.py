# ruff: noqa: RUF001 (intentional Cyrillic in Russian prompts)

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ravencode.runtime import agent_core as agent_mod
from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.permissions import PermissionAction, PermissionManager, PermissionRule
from ravencode.runtime.question import QuestionError


def _patch_save(monkeypatch) -> Any:
    fake = AsyncMock()
    monkeypatch.setattr("ravencode.runtime.session.get_session_store", lambda: fake)
    return fake


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


class TestEventEmitterSingle:
    @pytest.mark.asyncio
    async def test_single_handler_exception_logged(self):
        ee = EventEmitter()

        async def bad(event: AgentEvent) -> None:
            raise RuntimeError("handler boom")

        ee.on("evt", bad)
        await ee.emit(AgentEvent("evt"))


class TestLastAgent:
    def test_last_agent(self):
        agent = ReActAgent(config=AgentConfig())
        agent_mod._last_agent_var.set(agent)
        assert ReActAgent.last_agent() is agent


class TestReActAgentInit:
    def test_max_steps_override(self):
        agent = ReActAgent(config=AgentConfig(), max_steps=7)
        assert agent.config.max_steps == 7

    def test_passed_conversation(self):
        conv = Conversation(system_prompt="custom")
        agent = ReActAgent(config=AgentConfig(), conversation=conv)
        assert agent.conversation is conv

    def test_plan_mode_sets_deny_rules(self, monkeypatch):
        captured: list[Callable[[str, dict[str, Any]], tuple[bool, str]]] = []
        monkeypatch.setattr("ravencode.runtime.agent_core.set_permission_checker", lambda fn: captured.append(fn))
        ReActAgent(config=AgentConfig(plan_mode=True))
        assert captured
        assert captured[0]("bash", {}) == (False, "not allowed in read-only mode")

    def test_permissions_used(self, monkeypatch):
        captured: list[Callable[[str, dict[str, Any]], tuple[bool, str]]] = []
        monkeypatch.setattr("ravencode.runtime.agent_core.set_permission_checker", lambda fn: captured.append(fn))
        pm = PermissionManager([PermissionRule("x", PermissionAction.DENY, "no")])
        ReActAgent(config=AgentConfig(permissions=pm))
        assert captured[0]("x", {}) == (False, "no")

    def test_default_checker_allows(self, monkeypatch):
        captured: list[Callable[[str, dict[str, Any]], tuple[bool, str]]] = []
        monkeypatch.setattr("ravencode.runtime.agent_core.set_permission_checker", lambda fn: captured.append(fn))
        ReActAgent(config=AgentConfig())
        assert captured[0]("anything", {}) == (True, "")


class TestSystemPrompt:
    def test_structured_output_extra(self):
        agent = ReActAgent(config=AgentConfig(structured_output=True))
        assert "valid JSON" in agent._build_system_prompt()

    def test_plan_mode_extra(self):
        agent = ReActAgent(config=AgentConfig(plan_mode=True))
        assert "PLAN MODE" in agent._build_system_prompt()

    def test_default_system_prompt(self):
        assert "Raven" in ReActAgent._default_system_prompt()

    def test_build_uses_agents_md(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "AGENTS.md").write_text("repo instructions", encoding="utf-8")
        monkeypatch.setattr(agent_mod, "__file__", str(tmp_path / "pkg" / "core.py"))
        agent = ReActAgent(config=AgentConfig(proactive_scan=False, diff_preview=False))
        assert "repo instructions" in agent._build_system_prompt()


class TestArtifactBlocks:
    def test_full_blocks(self, monkeypatch):
        skill = SimpleNamespace(name="s1", instructions="do x", examples=["e1", "e2"])
        rule = SimpleNamespace(name="r1", content="must")
        command = SimpleNamespace(name="cmd", description="desc")
        manager = SimpleNamespace(
            context=MagicMock(),
            rules_for=MagicMock(return_value=[rule]),
            skills_for=MagicMock(return_value=[skill]),
            commands_for=MagicMock(return_value=[command]),
        )
        monkeypatch.setattr("raven.core.artifacts.get_artifact_manager", lambda cwd: manager)
        agent = ReActAgent(config=AgentConfig())
        text = agent._artifact_blocks()
        assert "[project rules]" in text
        assert "[skill: s1]" in text
        assert "Examples:" in text
        assert "[available commands]" in text

    def test_no_blocks(self, monkeypatch):
        manager = SimpleNamespace(
            context=MagicMock(),
            rules_for=MagicMock(return_value=[]),
            skills_for=MagicMock(return_value=[]),
            commands_for=MagicMock(return_value=[]),
        )
        monkeypatch.setattr("raven.core.artifacts.get_artifact_manager", lambda cwd: manager)
        agent = ReActAgent(config=AgentConfig())
        assert agent._artifact_blocks() == ""

    def test_exception_skipped(self, monkeypatch):
        monkeypatch.setattr(
            "raven.core.artifacts.get_artifact_manager", MagicMock(side_effect=RuntimeError("boom"))
        )
        agent = ReActAgent(config=AgentConfig())
        assert agent._artifact_blocks() == ""


class TestAbort:
    async def test_abort_cancels_task(self):
        agent = ReActAgent(config=AgentConfig())

        async def endless() -> None:
            await asyncio.sleep(10)

        task = asyncio.create_task(endless())
        agent._task = task
        agent.abort()
        assert agent._aborted is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestRunBranches:
    async def test_run_cancelled(self, monkeypatch):
        agent = ReActAgent(config=AgentConfig())
        _patch_save(monkeypatch)
        agent._run_impl = AsyncMock(side_effect=asyncio.CancelledError())  # type: ignore[method-assign]
        assert await agent.run("x") == "[aborted]"

    async def test_run_exception(self, monkeypatch):
        agent = ReActAgent(config=AgentConfig())
        _patch_save(monkeypatch)
        agent._run_impl = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        assert await agent.run("x") == "[error: boom]"

    def test_build_message_content(self):
        assert ReActAgent._build_message_content("hi", None) == "hi"
        blocks = ReActAgent._build_message_content("hi", ["http://x.png", "data:image/png;base64,xx", "raw"])
        assert isinstance(blocks, list)
        assert blocks[1]["image_url"]["url"] == "http://x.png"
        assert blocks[2]["image_url"]["url"].startswith("data:")
        assert blocks[3]["image_url"]["url"].startswith("data:image/png;base64,raw")

    async def test_run_aborted_in_loop(self, monkeypatch):
        events: list[str] = []
        ee = EventEmitter()

        async def on_done(e: AgentEvent) -> None:
            events.append(e.data["reason"])

        ee.on("done", on_done)

        async def fake_llm(messages):
            agent._aborted = True
            return {
                "content": "",
                "tool_calls": [{"id": "1", "function": {"name": "read", "arguments": {}}}],
            }

        agent = ReActAgent(config=AgentConfig(proactive_scan=False, diff_preview=False, event_emitter=ee), llm_provider=fake_llm)
        _patch_save(monkeypatch)
        result = await agent.run("x")
        assert result == "[aborted]"
        assert "aborted" in events


class TestCompleteFlow:
    async def test_final_answer_emits(self, monkeypatch):
        events: list[str] = []
        ee = EventEmitter()
        ee.on("message", lambda e: events.append("message"))  # type: ignore[arg-type,return-value]
        ee.on("done", lambda e: events.append("done"))  # type: ignore[arg-type,return-value]
        steps: list[int] = []
        messages: list[str] = []

        async def on_step(msg: str, step: int) -> None:
            steps.append(step)

        async def on_message(msg: dict[str, Any]) -> None:
            messages.append(msg["role"])

        async def fake_llm(messages):
            return {"content": "final answer"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, event_emitter=ee, on_step=on_step, on_message=on_message),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        result = await agent.run("task")
        assert result == "final answer"
        assert "message" in events and "done" in events
        assert steps == [1]

    async def test_proactive_scan_in_flow(self, monkeypatch):
        calls: list[int] = []

        async def fake_llm(messages):
            calls.append(1)
            if len(calls) == 1:
                return {"content": "probe files"}
            return {"content": "final"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=True, diff_preview=False, confirm_dangerous=False, max_steps=3),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        assert await agent.run("task") == "final"
        assert any("[proactive scan" in m.get("content", "") for m in agent.conversation.messages)

    async def test_tool_call_full_flow(self, monkeypatch):
        events: list[str] = []
        ee = EventEmitter()

        def make_handler(tag: str) -> Callable[[AgentEvent], Awaitable[None]]:
            async def handler(event: AgentEvent) -> None:
                events.append(tag)

            return handler

        for t in ("step_start", "tool_call", "tool_result", "done"):
            ee.on(t, make_handler(t))

        results: dict[str, str] = {}

        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            results[name] = str(args.get("path"))
            return "done"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        tool_events: list[str] = []
        steps: list[int] = []
        tool_msgs: list[str] = []

        async def on_step(msg: str, step: int) -> None:
            steps.append(step)

        async def on_message(msg: dict[str, Any]) -> None:
            tool_msgs.append(msg["role"])

        async def fake_llm(messages):
            return {
                "content": "thinking",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "read", "arguments": {"path": "a.py"}}}
                ],
            }

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, event_emitter=ee, on_step=on_step, on_message=on_message, max_steps=3),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        result = await agent.run("task")
        assert result == "[reached max steps]"
        assert "step_start" in events
        assert "tool_call" in events
        assert "tool_result" in events
        assert "done" in events
        assert "tool" in tool_msgs

    async def test_tool_call_args_dict_and_list(self, monkeypatch):
        calls: list[dict[str, object]] = []

        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            calls.append({"name": name, "args": args})
            return "ok"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)

        async def fake_llm(messages):
            if len(calls) == 0:
                return {
                    "content": "",
                    "tool_calls": [
                        {"id": "1", "function": {"name": "read", "arguments": {"path": "a"}}},
                        {"id": "2", "function": {"name": "read", "arguments": ["x"]}},
                    ],
                }
            return {"content": "final"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, max_steps=5),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        assert await agent.run("t") == "final"
        assert calls[0]["args"] == {"path": "a"}
        assert calls[1]["args"] == {"value": "['x']"}

    async def test_user_denied(self, monkeypatch):
        async def deny(name: str, args: dict[str, Any]) -> bool:
            return False

        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            raise AssertionError("should not execute")

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)

        async def fake_llm(messages):
            return {
                "content": "",
                "tool_calls": [{"id": "1", "function": {"name": "write", "arguments": {"path": "a"}}}],
            }

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=True, confirm_callback=deny, max_steps=5),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        result = await agent.run("t")
        assert result == "final" or result == "[reached max steps]"

    async def test_artifact_created_event(self, monkeypatch):
        events: list[dict[str, object]] = []
        ee = EventEmitter()
        ee.on("artifact_created", lambda e: events.append(e.data))  # type: ignore[arg-type,return-value]

        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            return '{"artifact_id": "a1", "title": "T", "type": "markdown"}'

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)

        async def fake_llm(messages):
            return {
                "content": "",
                "tool_calls": [
                    {"id": "1", "function": {"name": "create_artifact", "arguments": {"content": "x"}}}
                ],
            }

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, event_emitter=ee, max_steps=5),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        await agent.run("t")
        assert events and events[0]["artifact_id"] == "a1"

    async def test_artifact_created_invalid_json(self, monkeypatch):
        async def fake_execute(name: str, args: dict[str, Any]) -> str:
            return "not json"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)

        async def fake_llm(messages):
            return {
                "content": "",
                "tool_calls": [
                    {"id": "1", "function": {"name": "create_artifact", "arguments": {"content": "x"}}}
                ],
            }

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, max_steps=5),
            llm_provider=fake_llm,
        )
        _patch_save(monkeypatch)
        assert await agent.run("t") == "[reached max steps]"


class TestProactiveScan:
    async def test_scan_adds_message(self):
        async def fake_llm(messages):
            return {"content": "file1.py\nfile2.py"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=True, diff_preview=False, confirm_dangerous=False, max_steps=2),
            llm_provider=fake_llm,
        )
        await agent._proactive_scan("task")
        assert any("[proactive scan of task: task]" in m.get("content", "") for m in agent.conversation.messages)

    async def test_scan_exception(self, monkeypatch):
        async def fake_llm(messages):
            raise RuntimeError("llm down")

        agent = ReActAgent(config=AgentConfig(), llm_provider=fake_llm)
        await agent._proactive_scan("task")


class TestConfirmAction:
    async def test_non_dangerous(self):
        agent = ReActAgent(config=AgentConfig())
        assert await agent._confirm_action("read", {}) is True

    async def test_plan_mode_blocks(self):
        agent = ReActAgent(config=AgentConfig(plan_mode=True))
        assert await agent._confirm_action("bash", {}) is False

    async def test_confirm_disabled(self):
        agent = ReActAgent(config=AgentConfig(confirm_dangerous=False))
        assert await agent._confirm_action("bash", {}) is True

    async def test_callback_result(self):
        async def cb(name, args):
            return False

        agent = ReActAgent(config=AgentConfig(confirm_callback=cb))
        assert await agent._confirm_action("bash", {}) is False

    async def test_default_denies_without_callback(self):
        agent = ReActAgent(config=AgentConfig(confirm_dangerous=True))
        assert await agent._confirm_action("bash", {}) is False


class TestDiffPreview:
    async def test_disabled(self):
        agent = ReActAgent(config=AgentConfig(diff_preview=False))
        assert await agent._diff_preview("edit", {}) is None

    async def test_non_edit(self):
        agent = ReActAgent(config=AgentConfig())
        assert await agent._diff_preview("write", {}) is None

    async def test_preview_flag(self):
        agent = ReActAgent(config=AgentConfig())
        assert await agent._diff_preview("edit", {"preview": True}) is None

    async def test_returns_diff(self, monkeypatch):
        async def fake_execute(name, args):
            return "[diff] a"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        agent = ReActAgent(config=AgentConfig())
        result = await agent._diff_preview("edit", {"path": "a.py"})
        assert result == "[diff] a"

    async def test_non_diff_result(self, monkeypatch):
        async def fake_execute(name, args):
            return "no diff"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        agent = ReActAgent(config=AgentConfig())
        assert await agent._diff_preview("edit", {"path": "a.py"}) is None


class TestExecuteWithRetry:
    async def test_success(self, monkeypatch):
        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", AsyncMock(return_value="out"))
        agent = ReActAgent(config=AgentConfig(auto_format=False))
        assert await agent._execute_with_retry("read", {}) == "out"

    async def test_list_result(self, monkeypatch):
        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", AsyncMock(return_value=["a", "b"]))
        agent = ReActAgent(config=AgentConfig(auto_format=False))
        assert await agent._execute_with_retry("read", {}) == "a\nb"

    async def test_diff_preview_required(self, monkeypatch):
        agent = ReActAgent(config=AgentConfig(auto_format=False))
        agent._diff_preview = AsyncMock(return_value="[diff] x")  # type: ignore[method-assign]
        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", AsyncMock(return_value=["line1", "line2"]))
        result = await agent._execute_with_retry("edit", {"path": "a.py"})
        assert "diff preview required" in result
        assert "line1" in result

    async def test_diff_preview_flag_direct(self, monkeypatch):
        agent = ReActAgent(config=AgentConfig(auto_format=False))
        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", AsyncMock(return_value="preview text"))
        result = await agent._execute_with_retry("edit", {"path": "a.py", "preview": True})
        assert result == "preview text"

    async def test_auto_format(self, monkeypatch):
        calls: list[tuple[str, str]] = []

        async def fake_execute(name, args):
            calls.append((name, args.get("path", "")))
            return "ok"

        async def fake_format(path: str) -> str:
            return "formatted"

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        monkeypatch.setattr("ravencode.runtime.formatters.format_file", fake_format)
        agent = ReActAgent(config=AgentConfig(auto_format=True))
        assert await agent._execute_with_retry("write", {"path": "a.py"}) == "ok"

    async def test_auto_format_exception(self, monkeypatch):
        async def fake_execute(name, args):
            return "ok"

        async def fake_format(path: str) -> str:
            raise RuntimeError("fmt boom")

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        monkeypatch.setattr("ravencode.runtime.formatters.format_file", fake_format)
        agent = ReActAgent(config=AgentConfig(auto_format=True))
        assert await agent._execute_with_retry("write", {"path": "a.py"}) == "ok"

    async def test_retries_exhausted(self, monkeypatch):
        async def fake_execute(name, args):
            raise RuntimeError("always fails")

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        monkeypatch.setattr("ravencode.runtime.agent_core.asyncio.sleep", AsyncMock())
        agent = ReActAgent(config=AgentConfig(auto_format=False, max_tool_retries=2))
        result = await agent._execute_with_retry("read", {})
        assert result == "[error after 2 attempts]: always fails"

    async def test_question_error_reraises(self, monkeypatch):
        async def fake_execute(name, args):
            raise QuestionError({"question": "q"})

        monkeypatch.setattr("ravencode.runtime.agent_core.execute_tool", fake_execute)
        agent = ReActAgent(config=AgentConfig(auto_format=False))
        with pytest.raises(QuestionError):
            await agent._execute_with_retry("read", {})


class TestLlmCall:
    async def test_provider_dict(self):
        agent = ReActAgent(config=AgentConfig(), llm_provider=AsyncMock(return_value={"content": "hi"}))
        assert await agent._llm_call([]) == {"content": "hi"}

    async def test_provider_non_dict(self):
        agent = ReActAgent(config=AgentConfig(), llm_provider=AsyncMock(return_value="plain"))
        assert await agent._llm_call([]) == {"content": "plain"}

    async def test_aios_client_timeout(self, monkeypatch):
        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def ask_messages(self, messages, tools=None):
                raise TimeoutError()

        monkeypatch.setattr("ravencode.runtime.agent_core.AIOSClient", lambda: _FakeClient())
        monkeypatch.setattr("ravencode.runtime.agent_core.get_tool_definitions", lambda **kw: [])
        agent = ReActAgent(config=AgentConfig())
        result = await agent._llm_call([])
        assert result["content"] == "[error: LLM call timed out]"

    async def test_aios_client_success(self, monkeypatch):
        resp = SimpleNamespace(
            text="answer",
            tool_calls=[{"id": "c1", "name": "read", "arguments": {"path": "a"}}],
        )

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def ask_messages(self, messages, tools=None):
                return resp

        monkeypatch.setattr("ravencode.runtime.agent_core.AIOSClient", lambda: _FakeClient())
        monkeypatch.setattr("ravencode.runtime.agent_core.get_tool_definitions", lambda **kw: [])
        agent = ReActAgent(config=AgentConfig())
        result = await agent._llm_call([])
        assert result["content"] == "answer"
        assert result["tool_calls"][0]["function"]["name"] == "read"


class TestAutoSave:
    async def test_save_exception(self, monkeypatch):
        def boom():
            raise RuntimeError("no store")

        monkeypatch.setattr("ravencode.runtime.session.get_session_store", boom)
        agent = ReActAgent(config=AgentConfig())
        await agent._auto_save("complete")


class TestSerialization:
    def test_dump_state(self):
        agent = ReActAgent(config=AgentConfig(max_steps=9), conversation=Conversation(system_prompt="s"))
        state = agent.dump_state()
        assert state["name"] == "raven"
        assert state["config"]["max_steps"] == 9

    def test_load_state(self):
        state = {"name": "restored", "config": {"max_steps": 4}, "conversation": []}
        agent = ReActAgent.load_state(state)
        assert agent.name == "restored"
        assert agent.config.max_steps == 4


class TestReActAgentReflection:
    @pytest.mark.asyncio
    async def test_reflection_injected_at_step_5(self):
        from ravencode.runtime.agent_core import ReActAgent

        calls: list[object] = []

        async def fake_llm(messages):
            calls.append(messages)
            if len(calls) <= 5:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call_{len(calls)}",
                            "type": "function",
                            "function": {"name": "nodes_list", "arguments": "{}"},
                        }
                    ],
                }
            return {"content": "final answer"}

        agent = ReActAgent(
            config=AgentConfig(proactive_scan=False, diff_preview=False, confirm_dangerous=False, max_steps=20),
            llm_provider=fake_llm,
        )
        result = await agent.run("do the thing")
        assert result == "final answer"
        system_msgs = [m.get("content", "") for m in agent.conversation.messages if m.get("role") == "system"]
        assert any("Progress checkpoint" in s for s in system_msgs)


class TestMemoryContext:
    def test_no_memory_path_returns_empty(self):
        assert ReActAgent(config=AgentConfig(), conversation=Conversation(system_prompt="s"))._memory_context() == ""

    def test_memory_context_with_milestones(self, tmp_path):
        store_path = str(tmp_path / "mem.json")
        from ravencode.runtime.context import MemoryStore

        store = MemoryStore(path=store_path)
        store._data = {"milestones": ["setup", "implemented auth", "added tests"]}
        store._write(store._data)
        agent = ReActAgent(config=AgentConfig(memory_path=store_path), conversation=Conversation(system_prompt="s"))
        ctx = agent._memory_context()
        assert "Milestones" in ctx
        assert "implemented auth" in ctx

    def test_memory_context_with_recent_work(self, tmp_path):
        store_path = str(tmp_path / "mem2.json")
        from ravencode.runtime.context import MemoryStore

        store = MemoryStore(path=store_path)
        store._data = {"recent_work": ["refactored router", "added cache"]}
        store._write(store._data)
        agent = ReActAgent(config=AgentConfig(memory_path=store_path), conversation=Conversation(system_prompt="s"))
        ctx = agent._memory_context()
        assert "Recent work" in ctx
        assert "refactored router" in ctx

    def test_memory_context_handles_missing_keys(self, tmp_path):
        store_path = str(tmp_path / "mem3.json")
        from ravencode.runtime.context import MemoryStore

        store = MemoryStore(path=store_path)
        store._write({})
        agent = ReActAgent(config=AgentConfig(memory_path=store_path), conversation=Conversation(system_prompt="s"))
        assert agent._memory_context() == ""

