# ruff: noqa: RUF001 (intentional Cyrillic in Russian prompts)

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from aios.api.bridge import (
    AgentDispatchRequest,
    AIRequest,
    ExecRequest,
    MultiAgentRequest,
    TruthfulRequest,
    _require_ws_auth,
    _ws_auth_payload,
    aios_agent_dispatch,
    aios_agent_truthful,
    aios_agent_ws,
    aios_delete_session,
    aios_exec,
    aios_gateway,
    aios_health,
    aios_list_sessions,
    aios_metrics,
    aios_metrics_prometheus,
    aios_multi_agent,
    aios_websocket,
    router,
)
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
    async def test_truthful_endpoint_wraps_llm_error(self):
        from aios.api.bridge import TruthfulRequest, aios_agent_truthful

        async def boom(prompt: str, context: str, model: str | None = None) -> None:
            raise RuntimeError("All LLM providers exhausted")

        with patch("aios.api.bridge.run_truthful", boom):
            resp = await aios_agent_truthful(TruthfulRequest(prompt="q"))
        assert resp.status == "error"
        assert resp.content == "[error: All LLM providers exhausted]"

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


class _FakeWS:
    def __init__(
        self,
        *,
        token: str | None = None,
        messages: list[Any] | None = None,
    ) -> None:
        self.query_params = {"token": token} if token else {}
        self._messages = list(messages or [])
        self._i = 0
        self.sent: list[dict[str, Any]] = []
        self.closed: list[tuple[int, str]] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if self._i >= len(self._messages):
            raise WebSocketDisconnect()
        msg = self._messages[self._i]
        self._i += 1
        return msg if isinstance(msg, str) else json.dumps(msg)

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


class _FakeClient:
    async def ask(self, prompt: str, task: str, model: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(text=f"answer:{task}", model=model or "m", provider="p")

    async def ask_stream(self, messages: Any, tools: Any = None, model: Any = None) -> Any:
        yield "tok1"
        yield "tok2"


def _mk_results() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            index=0,
            description="d",
            result=SimpleNamespace(success=True, data={"x": 1}, error=None),
            duration=0.5,
        )
    ]


class TestAiosBridgeEndpoints:
    @pytest.mark.asyncio
    async def test_gateway(self, monkeypatch) -> None:
        monkeypatch.setattr("aios.api.bridge._client", _FakeClient())
        resp = await aios_gateway(AIRequest(prompt="p", task="code", model="mm"))
        assert resp.text == "answer:code"
        assert resp.model == "mm"
        assert resp.provider == "p"

    @pytest.mark.asyncio
    async def test_exec_success(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.runtime.adapter.RuntimeAdapter.run_command", AsyncMock(return_value="out")
        )
        resp = await aios_exec(ExecRequest(command="ls"))
        assert resp.output == "out"
        assert resp.error is None

    @pytest.mark.asyncio
    async def test_exec_error(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.runtime.adapter.RuntimeAdapter.run_command",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        resp = await aios_exec(ExecRequest(command="ls"))
        assert resp.output == ""
        assert resp.error == "boom"

    @pytest.mark.asyncio
    async def test_agent_dispatch_valid(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge._orch",
            SimpleNamespace(
                dispatch=AsyncMock(
                    return_value=SimpleNamespace(
                        agent="planner", success=True, data={"plan": "x"}, error=None, steps=2
                    )
                )
            ),
        )
        resp = await aios_agent_dispatch(AgentDispatchRequest(task="t", agent_type="planner"))
        assert resp.success is True
        assert resp.agent == "planner"
        assert resp.data == {"plan": "x"}
        assert resp.steps == 2

    @pytest.mark.asyncio
    async def test_agent_dispatch_invalid_type(self) -> None:
        resp = await aios_agent_dispatch(AgentDispatchRequest(task="t", agent_type="nope"))
        assert resp.success is False
        assert resp.error is not None
        assert "Invalid agent type" in resp.error
        assert "planner" in resp.error

    @pytest.mark.asyncio
    async def test_truthful_endpoint_success(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.run_truthful",
            AsyncMock(return_value=SimpleNamespace(status="success", content="ok", thinking_process="tp")),
        )
        resp = await aios_agent_truthful(TruthfulRequest(prompt="q"))
        assert resp.status == "success"
        assert resp.content == "ok"
        assert resp.thinking_process == "tp"

    @pytest.mark.asyncio
    async def test_multi_parallel(self, monkeypatch) -> None:
        fake = SimpleNamespace(
            run_parallel=AsyncMock(return_value=_mk_results()),
            run_dag=AsyncMock(),
            run_sequential=AsyncMock(),
        )
        monkeypatch.setattr("aios.api.bridge._multi", fake)
        req = MultiAgentRequest(
            tasks=[{"description": "d", "agent_type": "autonomous", "depends_on": None}],
            mode="parallel",
            max_concurrent=3,
        )
        resp = await aios_multi_agent(req)
        assert fake.run_parallel.await_count == 1
        assert resp[0]["success"] is True
        assert resp[0]["data"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_multi_dag(self, monkeypatch) -> None:
        fake = SimpleNamespace(
            run_parallel=AsyncMock(),
            run_dag=AsyncMock(return_value=_mk_results()),
            run_sequential=AsyncMock(),
        )
        monkeypatch.setattr("aios.api.bridge._multi", fake)
        req = MultiAgentRequest(tasks=[{"description": "d"}], mode="dag")
        resp = await aios_multi_agent(req)
        assert fake.run_dag.await_count == 1
        assert resp[0]["description"] == "d"

    @pytest.mark.asyncio
    async def test_multi_sequential_default(self, monkeypatch) -> None:
        fake = SimpleNamespace(
            run_parallel=AsyncMock(),
            run_dag=AsyncMock(),
            run_sequential=AsyncMock(return_value=_mk_results()),
        )
        monkeypatch.setattr("aios.api.bridge._multi", fake)
        req = MultiAgentRequest(tasks=[{"description": "d"}], mode="bogus")
        resp = await aios_multi_agent(req)
        assert fake.run_sequential.await_count == 1
        assert resp[0]["duration"] == 0.5

    @pytest.mark.asyncio
    async def test_list_sessions(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge._session_store", SimpleNamespace(list=lambda: [{"id": "s1"}])
        )
        resp = await aios_list_sessions()
        assert resp == {"sessions": [{"id": "s1"}]}

    @pytest.mark.asyncio
    async def test_delete_session(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge._session_store",
            SimpleNamespace(list=lambda: [], delete=AsyncMock(return_value=True)),
        )
        resp = await aios_delete_session("s1")
        assert resp == {"deleted": True}

    @pytest.mark.asyncio
    async def test_health(self) -> None:
        resp = await aios_health()
        assert resp == {"status": "ok", "module": "ai-os-mvp", "version": "0.1.0"}

    @pytest.mark.asyncio
    async def test_metrics(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "raven.core.metrics.metrics", SimpleNamespace(snapshot=lambda: {"x": 1})
        )
        resp = await aios_metrics()
        assert resp == {"x": 1}

    @pytest.mark.asyncio
    async def test_metrics_prometheus(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "raven.core.metrics.metrics",
            SimpleNamespace(prometheus=lambda: "# HELP foo"),
        )
        resp = await aios_metrics_prometheus()
        assert resp == "# HELP foo"


class TestAiosWebSocketAuth:
    @pytest.mark.asyncio
    async def test_auth_payload_no_token(self) -> None:
        assert await _ws_auth_payload(_FakeWS()) is None  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_auth_payload_secret_token(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.settings.web_secret_key",
            SimpleNamespace(get_secret_value=lambda: "topsecret"),
        )
        payload = await _ws_auth_payload(_FakeWS(token="topsecret"))  # type: ignore[arg-type]
        assert payload == {"sub": "admin", "role": "admin"}

    @pytest.mark.asyncio
    async def test_auth_payload_decodes_jwt(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.settings.web_secret_key",
            SimpleNamespace(get_secret_value=lambda: "real"),
        )
        monkeypatch.setattr(
            "raven.core.auth.auth_handler.auth_handler",
            SimpleNamespace(decode_token=AsyncMock(return_value={"sub": "user"})),
        )
        payload = await _ws_auth_payload(_FakeWS(token="jwt-here"))  # type: ignore[arg-type]
        assert payload == {"sub": "user"}

    @pytest.mark.asyncio
    async def test_require_auth_rejects(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge._ws_auth_payload", AsyncMock(return_value=None)
        )
        ws = _FakeWS()
        payload = await _require_ws_auth(ws)  # type: ignore[arg-type]
        assert payload is None
        assert ws.closed == [(1008, "Authentication required")]

    @pytest.mark.asyncio
    async def test_require_auth_accepts(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge._ws_auth_payload", AsyncMock(return_value={"sub": "admin"})
        )
        ws = _FakeWS()
        payload = await _require_ws_auth(ws)  # type: ignore[arg-type]
        assert payload == {"sub": "admin"}
        assert ws.closed == []


class TestAiosWebSocket:
    @pytest.mark.asyncio
    async def test_websocket_unauthenticated(self) -> None:
        ws = _FakeWS(messages=[{"action": "ping"}])
        await aios_websocket(ws)  # type: ignore[arg-type]
        assert ws.closed == [(1008, "Authentication required")]
        assert ws.accepted is False

    @pytest.mark.asyncio
    async def test_websocket_full_flow(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.settings.web_secret_key",
            SimpleNamespace(get_secret_value=lambda: "topsecret"),
        )
        monkeypatch.setattr("aios.api.bridge._client", _FakeClient())
        monkeypatch.setattr(
            "aios.api.bridge._orch",
            SimpleNamespace(
                dispatch=AsyncMock(
                    return_value=SimpleNamespace(
                        agent="planner", success=True, data={"plan": "x"}, error=None, steps=2
                    )
                )
            ),
        )
        ws = _FakeWS(
            token="topsecret",
            messages=[
                "not json",
                {"action": "ask", "prompt": "hi"},
                {"action": "ask_stream", "messages": [{"role": "user", "content": "m"}], "tools": [], "model": "mm"},
                {"action": "agent", "task": "do", "agent_type": "planner"},
                {"action": "ping"},
                {"action": "bogus"},
            ],
        )
        await aios_websocket(ws)  # type: ignore[arg-type]
        assert ws.accepted
        tags = [m.get("type") or m.get("error") for m in ws.sent]
        assert "invalid JSON" in tags
        assert "result" in tags
        assert "stream_start" in tags
        assert "token" in tags
        assert "stream_end" in tags
        assert "agent_result" in tags
        assert "pong" in tags
        assert "unknown action: bogus" in tags


class TestAiosAgentWebSocketEndpoint:
    @pytest.mark.asyncio
    async def test_agent_ws_full_flow(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.settings.web_secret_key",
            SimpleNamespace(get_secret_value=lambda: "topsecret"),
        )
        agent_run: dict[str, str] = {"value": "final answer"}
        truthful_raise = {"value": False}

        class _FakeReActAgent:
            def __init__(self, config: Any = None) -> None:
                self.config = config

            async def run(self, prompt: str) -> str:
                return agent_run["value"]

        async def _fake_run_truthful(prompt: str, context: str, model: str | None = None) -> SimpleNamespace:
            if truthful_raise["value"]:
                raise ValueError("model not found")
            return SimpleNamespace(status="success", content="truth", thinking_process="tp")

        monkeypatch.setattr("aios.api.bridge.ReActAgent", _FakeReActAgent)
        monkeypatch.setattr("aios.api.bridge.run_truthful", _fake_run_truthful)

        ws = _FakeWS(
            token="topsecret",
            messages=[
                "not json",
                {"prompt": ""},
                {"prompt": "q", "truthful": True},
                {"prompt": "q"},
            ],
        )
        await aios_agent_ws(ws)  # type: ignore[arg-type]
        messages = ws.sent
        assert ws.accepted
        types = [m.get("type") for m in messages]
        assert types.count("error") == 2
        assert types.count("final") == 2
        assert any(m.get("data", {}).get("message") == "invalid JSON" for m in messages)
        assert any(m.get("data", {}).get("message") == "prompt required" for m in messages)
        finals = [m["data"] for m in messages if m.get("type") == "final"]
        assert {"status": "success", "content": "truth", "thinking_process": "tp"} in finals
        assert {"content": "final answer"} in finals

    @pytest.mark.asyncio
    async def test_agent_ws_truthful_error_and_aborted(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.settings.web_secret_key",
            SimpleNamespace(get_secret_value=lambda: "topsecret"),
        )
        agent_run: dict[str, str] = {"value": "[aborted by user]"}

        class _FakeReActAgent:
            def __init__(self, config: Any = None) -> None:
                self.config = config

            async def run(self, prompt: str) -> str:
                return agent_run["value"]

        async def _fake_run_truthful(prompt: str, context: str, model: str | None = None) -> None:
            raise ValueError("model not found")

        monkeypatch.setattr("aios.api.bridge.ReActAgent", _FakeReActAgent)
        monkeypatch.setattr("aios.api.bridge.run_truthful", _fake_run_truthful)

        ws = _FakeWS(
            token="topsecret",
            messages=[
                {"prompt": "q", "truthful": True},
                {"prompt": "q"},
            ],
        )
        await aios_agent_ws(ws)  # type: ignore[arg-type]
        messages = ws.sent
        assert any(m.get("data", {}).get("message") == "model not found" for m in messages)
        assert all(m.get("type") != "final" for m in messages)

    @pytest.mark.asyncio
    async def test_agent_ws_unauthenticated(self) -> None:
        ws = _FakeWS(messages=[{"prompt": "q"}])
        await aios_agent_ws(ws)  # type: ignore[arg-type]
        assert ws.closed == [(1008, "Authentication required")]
        assert ws.accepted is False

    @pytest.mark.asyncio
    async def test_agent_ws_send_event_exception(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "aios.api.bridge.settings.web_secret_key",
            SimpleNamespace(get_secret_value=lambda: "topsecret"),
        )

        class _BoomWS(_FakeWS):
            def __init__(self) -> None:
                super().__init__(token="topsecret", messages=[{"prompt": "q"}])
                self._sent = 0

            async def send_json(self, data: dict[str, Any]) -> None:
                self._sent += 1
                if self._sent == 1:
                    raise RuntimeError("client gone")
                await super().send_json(data)

        class _EmittingAgent:
            def __init__(self, config: Any = None) -> None:
                self.config = config

            async def run(self, prompt: str) -> str:
                if self.config.event_emitter is not None:
                    await self.config.event_emitter.emit(
                        AgentEvent("message", {"role": "user", "content": "x"})
                    )
                return "ok"

        monkeypatch.setattr("aios.api.bridge.ReActAgent", _EmittingAgent)
        ws = _BoomWS()
        await aios_agent_ws(ws)  # type: ignore[arg-type]
        assert any(m.get("type") == "final" and m.get("data", {}).get("content") == "ok" for m in ws.sent)
