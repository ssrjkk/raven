"""Concurrency and confirmation-callback coverage for aios `/ws/agent`.

These tests drive the WebSocket endpoint with a controllable fake that keeps a
single reader per phase, so ``asyncio`` task scheduling stays deterministic:
the endpoint's background ``recv_task`` parks while an agent runs, and the
``_confirm`` callback reads from a dedicated inbox it never competes for.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import WebSocketDisconnect

import aios.api.bridge as bridge
from aios.api.bridge import aios_agent_ws


class _CtlWS:
    def __init__(
        self,
        *,
        main: list[Any] | None = None,
        ctrl: list[Any] | None = None,
        confirm_inbox: list[Any] | None = None,
        behaviors: list[str] | None = None,
        bg: str = "park",
    ) -> None:
        self.query_params = {"token": "topsecret"}
        self._main = list(main or [])
        self._ctrl = list(ctrl or [])
        self._confirm_inbox = list(confirm_inbox or [])
        self._behaviors = list(behaviors or [])
        self._bg = bg
        self._agent_running = False
        self._in_confirm = False
        self.accepted = False
        self.sent: list[dict[str, Any]] = []
        self.confirm_results: list[bool] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        return None

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def receive_text(self) -> str:
        if self._in_confirm:
            if not self._confirm_inbox:
                await asyncio.Event().wait()
            item = self._confirm_inbox.pop(0)
            return item if isinstance(item, str) else json.dumps(item)
        if self._agent_running:
            if self._ctrl:
                item = self._ctrl.pop(0)
                return item if isinstance(item, str) else json.dumps(item)
            if self._bg == "raise":
                raise WebSocketDisconnect()
            await asyncio.Event().wait()
        if not self._main:
            raise WebSocketDisconnect()
        item = self._main.pop(0)
        return item if isinstance(item, str) else json.dumps(item)


def _install(ws: _CtlWS, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aios.api.bridge.settings.web_secret_key",
        SimpleNamespace(get_secret_value=lambda: "topsecret"),
    )

    class _FakeReActAgent:
        def __init__(self, config: Any = None) -> None:
            self.config = config

        async def run(self, _prompt: str) -> str:
            ws._agent_running = True
            await asyncio.sleep(0)  # yield so the background recv_task parks first
            behavior = ws._behaviors.pop(0) if ws._behaviors else "quick"
            try:
                if behavior == "slow":
                    await asyncio.Event().wait()  # park until cancelled
                    return "never"
                if behavior.startswith("confirm"):
                    cb = self.config.confirm_callback
                    ws._in_confirm = True
                    try:
                        approved = await cb("write_file", {"path": "p.txt", "content": "c"})
                    finally:
                        ws._in_confirm = False
                    ws.confirm_results.append(bool(approved))
                    return f"confirm:{bool(approved)}"
                await asyncio.sleep(0)
                return "agent-done"
            finally:
                ws._agent_running = False

    monkeypatch.setattr(bridge, "ReActAgent", _FakeReActAgent)


@pytest.mark.asyncio
async def test_agent_ws_mcp_connect_exception_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aios.api.bridge.settings.web_secret_key",
        SimpleNamespace(get_secret_value=lambda: "topsecret"),
    )

    async def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("mcp unavailable")

    monkeypatch.setattr("ravencode.runtime.mcp_tools.ensure_mcp_tools", _boom)
    ws = _CtlWS(main=[])  # empty -> first sequential read disconnects
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.accepted is True


@pytest.mark.asyncio
async def test_agent_ws_completes_and_cancels_background_recv(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _CtlWS(main=[{"prompt": "go"}], behaviors=["quick"], bg="park")
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    final = [m for m in ws.sent if m.get("type") == "final"]
    assert final and final[0]["data"]["content"] == "agent-done"


@pytest.mark.asyncio
async def test_agent_ws_cancel_stops_running_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _CtlWS(
        main=[{"prompt": "go"}],
        ctrl=[{"type": "cancel"}],
        behaviors=["slow"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert any(m.get("type") == "done" and m.get("data", {}).get("reason") == "cancelled" for m in ws.sent)
    # the aborted agent must not emit a final answer
    assert all(m.get("type") != "final" for m in ws.sent)


@pytest.mark.asyncio
async def test_agent_ws_disconnect_while_agent_running_cancels_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = _CtlWS(main=[{"prompt": "go"}], behaviors=["slow"], bg="raise")
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.accepted is True
    assert all(m.get("type") != "final" for m in ws.sent)


@pytest.mark.asyncio
async def test_confirm_approve_with_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_compute_confirm_diff", lambda *_a: "DIFF-BODY")
    ws = _CtlWS(
        main=[{"prompt": "go"}],
        confirm_inbox=[{"type": "confirm", "data": {"approved": True}}],
        behaviors=["confirm"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.confirm_results == [True]
    req = [m for m in ws.sent if m.get("type") == "confirm_request"]
    assert req and req[0]["data"]["diff"] == "DIFF-BODY"


@pytest.mark.asyncio
async def test_confirm_deny_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_compute_confirm_diff", lambda *_a: None)
    ws = _CtlWS(
        main=[{"prompt": "go"}],
        confirm_inbox=[{"type": "deny"}],
        behaviors=["confirm"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.confirm_results == [False]


@pytest.mark.asyncio
async def test_confirm_invalid_json_reply_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_compute_confirm_diff", lambda *_a: None)
    ws = _CtlWS(
        main=[{"prompt": "go"}],
        confirm_inbox=["{ not valid json"],
        behaviors=["confirm"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.confirm_results == [False]


@pytest.mark.asyncio
async def test_confirm_ignores_unrelated_event_then_approves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge, "_compute_confirm_diff", lambda *_a: None)
    ws = _CtlWS(
        main=[{"prompt": "go"}],
        confirm_inbox=[
            {"type": "progress", "data": {}},
            {"type": "confirm", "data": {"approved": True}},
        ],
        behaviors=["confirm"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.confirm_results == [True]


@pytest.mark.asyncio
async def test_confirm_outer_exception_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("diff failed")

    monkeypatch.setattr(bridge, "_compute_confirm_diff", _boom)
    ws = _CtlWS(
        main=[{"prompt": "go"}],
        confirm_inbox=[{"type": "confirm", "data": {"approved": True}}],
        behaviors=["confirm"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    # _confirm swallowed the diff error and returned False (never sent confirm_request)
    assert ws.confirm_results == [False]
    assert not any(m.get("type") == "confirm_request" for m in ws.sent)


@pytest.mark.asyncio
async def test_confirm_deadline_exceeded_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    # _confirm computes ``remaining = deadline - loop.time()``; a non-terminal
    # first reply keeps the loop alive until the fake clock passes the 60s deadline.
    monkeypatch.setattr(bridge, "_compute_confirm_diff", lambda *_a: None)

    remaining_times = [0.0, 10.0, 61.0]

    def _fake_time() -> float:
        return remaining_times.pop(0) if remaining_times else 999.0

    fake_asyncio = SimpleNamespace(
        get_event_loop=lambda: SimpleNamespace(time=_fake_time),
        wait_for=asyncio.wait_for,
        create_task=asyncio.create_task,
        wait=asyncio.wait,
        Event=asyncio.Event,
        Task=asyncio.Task,
        sleep=asyncio.sleep,
        FIRST_COMPLETED=asyncio.FIRST_COMPLETED,
        CancelledError=asyncio.CancelledError,
    )
    monkeypatch.setattr(bridge, "asyncio", fake_asyncio)

    ws = _CtlWS(
        main=[{"prompt": "go"}],
        confirm_inbox=[{"type": "progress", "data": {}}],
        behaviors=["confirm"],
        bg="park",
    )
    _install(ws, monkeypatch)
    await aios_agent_ws(ws)  # type: ignore[arg-type]
    assert ws.confirm_results == [False]
