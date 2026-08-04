# ruff: noqa: RUF001 (intentional Cyrillic in Russian prompts)

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aios.api.bridge import router
from ravencode.runtime.agent_core import AgentEvent, EventEmitter


class TestAiosAgentWebSocket:
    @pytest.mark.asyncio
    async def test_router_includes_ws_agent(self):
        routes = [r.path for r in router.routes]  # type: ignore[attr-defined]
        assert "/aios/ws/agent" in routes

    @pytest.mark.asyncio
    async def test_router_includes_existing_routes(self):
        routes = [r.path for r in router.routes]  # type: ignore[attr-defined]
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


class TestAiosTruthful:
    @pytest.fixture(autouse=True)
    def _reset_router_cache(self):
        from aios.api import bridge as bridge_module

        bridge_module._reset_critical_router()
        yield
        bridge_module._reset_critical_router()

    @pytest.mark.asyncio
    async def test_router_includes_truthful_route(self):
        routes = [r.path for r in router.routes]  # type: ignore[attr-defined]
        assert "/aios/agent/truthful" in routes

    def test_truthful_request_rejects_empty_prompt(self):
        from pydantic import ValidationError

        from aios.api.bridge import TruthfulRequest

        with pytest.raises(ValidationError):
            TruthfulRequest(prompt="")

    def test_truthful_request_rejects_oversized_prompt(self):
        from pydantic import ValidationError

        from aios.api.bridge import TruthfulRequest

        with pytest.raises(ValidationError):
            TruthfulRequest(prompt="x" * 20_001)

    def test_truthful_request_rejects_oversized_context(self):
        from pydantic import ValidationError

        from aios.api.bridge import TruthfulRequest

        with pytest.raises(ValidationError):
            TruthfulRequest(prompt="q", context="x" * 20_001)

    @pytest.mark.asyncio
    async def test_run_truthful_rejects_oversized_prompt(self):
        from aios.api.bridge import run_truthful

        with pytest.raises(ValueError):
            await run_truthful("x" * 20_001, "", model="test-model")

    @pytest.mark.asyncio
    async def test_run_truthful_success(self):
        from aios.api.bridge import run_truthful
        from raven.core.agents.truthful_orchestrator import TruthfulResult
        from tests.core.test_truthful_orchestrator import ScriptedCompleter

        completer = ScriptedCompleter(
            [
                "<thinking>факт проверен</thinking>\nответ готов",
                "VERIFIED: TRUE",
            ]
        )
        with patch("raven.core.llm.LLMRouter", return_value=completer):
            result = await run_truthful("q", "context", model="test-model")
        assert isinstance(result, TruthfulResult)
        assert result.status == "success"
        assert result.content == "ответ готов"
        assert result.thinking_process == "факт проверен"

    @pytest.mark.asyncio
    async def test_run_truthful_corrected(self):
        from aios.api.bridge import run_truthful
        from tests.core.test_truthful_orchestrator import ScriptedCompleter

        completer = ScriptedCompleter(
            [
                "<thinking>первое</thinking>\nчерновик",
                "VERIFIED: FALSE: ошибка в ответе",
                "<thinking>второе</thinking>\nисправлено",
                "VERIFIED: TRUE",
            ]
        )
        with patch("raven.core.llm.LLMRouter", return_value=completer):
            result = await run_truthful("q", "", model="test-model")
        assert result.status == "corrected"
        assert result.content == "исправлено"

    @pytest.mark.asyncio
    async def test_run_truthful_passes_provider_config(self):
        from unittest.mock import patch as _patch

        from aios.api.bridge import run_truthful
        from tests.core.test_truthful_orchestrator import ScriptedCompleter

        captured: list[dict[str, Any]] = []

        class FakeLLMRouter(ScriptedCompleter):
            def __init__(self, providers_config: dict[str, Any] | None = None) -> None:
                captured.append(providers_config or {})
                super().__init__(["<thinking>x</thinking>\nответ", "VERIFIED: TRUE"])

        fake_key = MagicMock()
        fake_key.get_secret_value.return_value = "sk-test"
        with (
            _patch("raven.core.llm.LLMRouter", FakeLLMRouter),
            _patch("aios.api.bridge.settings.critical_provider", "openrouter"),
            _patch("aios.api.bridge.settings.critical_api_key", fake_key),
        ):
            result = await run_truthful("q", "", model="test-model")
        assert result.status == "success"
        assert captured == [{"openrouter": {"api_key": "sk-test"}}]
