from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.channels.webchat.streaming import AgentStreamHandler
from ravencode.runtime.agent_core import AgentEvent, EventEmitter


class TestAgentStreamHandler:
    @pytest.mark.asyncio
    async def test_build_event_emitter(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "session:1:stream")
        ee = handler.build_event_emitter()
        assert isinstance(ee, EventEmitter)
        assert "step_start" in ee._handlers
        assert "tool_call" in ee._handlers
        assert "tool_result" in ee._handlers
        assert "message" in ee._handlers
        assert "done" in ee._handlers

    @pytest.mark.asyncio
    async def test_on_step_start_sends_ws(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_step_start(AgentEvent("step_start", {"step": 1}))
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "step_start"
        assert call_args["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_on_tool_call_sends_ws(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_tool_call(AgentEvent("tool_call", {"name": "read", "args": {}}))
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "tool_call"
        assert call_args["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_on_tool_result_sends_ws(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_tool_result(AgentEvent("tool_result", {"name": "read", "result": "ok"}))
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "tool_result"

    @pytest.mark.asyncio
    async def test_on_message_sends_ws(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_message(AgentEvent("message", {"role": "assistant", "content": "hello"}))
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "message"

    @pytest.mark.asyncio
    async def test_on_done_sends_ws(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_done(AgentEvent("done", {"reason": "complete", "steps": 3}))
        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "done"

    @pytest.mark.asyncio
    async def test_send_handles_disconnect_gracefully(self):
        ws = MagicMock()
        ws.send_json = AsyncMock(side_effect=ConnectionError("disconnected"))
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_message(AgentEvent("message", {}))
        assert True

    @pytest.mark.asyncio
    async def test_send_handles_exception_gracefully(self):
        ws = MagicMock()
        ws.send_json = AsyncMock(side_effect=RuntimeError("boom"))
        handler = AgentStreamHandler(ws, "s1")
        await handler._on_message(AgentEvent("message", {}))
        assert True

    @pytest.mark.asyncio
    async def test_full_stream_lifecycle(self):
        ws = AsyncMock()
        handler = AgentStreamHandler(ws, "s1")
        ee = handler.build_event_emitter()

        await ee.emit(AgentEvent("step_start", {"step": 1}))
        await ee.emit(AgentEvent("tool_call", {"name": "read", "args": {"path": "x"}}))
        await ee.emit(AgentEvent("tool_result", {"name": "read", "result": "content"}))
        await ee.emit(AgentEvent("message", {"role": "assistant", "content": "done"}))
        await ee.emit(AgentEvent("done", {"reason": "complete", "steps": 1}))

        assert ws.send_json.call_count >= 5
