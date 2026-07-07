from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aios.api.bridge import router
from ravencode.runtime.agent_core import AgentEvent, EventEmitter


class TestAiosAgentWebSocket:
    @pytest.mark.asyncio
    async def test_router_includes_ws_agent(self):
        routes = [r.path for r in router.routes]
        assert "/aios/ws/agent" in routes

    @pytest.mark.asyncio
    async def test_router_includes_existing_routes(self):
        routes = [r.path for r in router.routes]
        assert "/aios/ws" in routes
        assert "/aios/health" in routes
        assert "/aios/ai" in routes

    @pytest.mark.asyncio
    async def test_agent_event_stream(self):
        ee = EventEmitter()
        received: list[AgentEvent] = []
        async def collector(event: AgentEvent) -> None:
            received.append(event)
        ee.on("step_start", collector)
        ee.on("tool_call", collector)
        ee.on("tool_result", collector)
        ee.on("message", collector)
        ee.on("done", collector)

        await ee.emit(AgentEvent("step_start", {"step": 1}))
        await ee.emit(AgentEvent("tool_call", {"name": "read", "args": {"path": "x"}}))
        await ee.emit(AgentEvent("tool_result", {"name": "read", "result": "content"}))
        await ee.emit(AgentEvent("message", {"role": "assistant", "content": "done"}))
        await ee.emit(AgentEvent("done", {"reason": "complete", "steps": 1}))

        types = [e.type for e in received]
        assert types == ["step_start", "tool_call", "tool_result", "message", "done"]

    @pytest.mark.asyncio
    async def test_agent_config_defaults_match_ws(self):
        from ravencode.runtime.agent_core import AgentConfig
        config = AgentConfig(max_steps=30, diff_preview=True, proactive_scan=True)
        assert config.max_steps == 30
        assert config.event_emitter is None
        assert config.diff_preview is True
