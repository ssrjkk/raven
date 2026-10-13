from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.gateway.intents import (
    BriefingIntent,
    MonitorIntent,
    PriceIntent,
    TaskIntent,
    handle_intent,
)
from raven.core.monitor.models import Monitor, MonitorStatus, MonitorType


class _FakeGateway:
    def __init__(self) -> None:
        self._send = AsyncMock()
        self._monitor_store = MagicMock()
        self._get_skill = MagicMock(return_value=None)
        self.tasks = SimpleNamespace(create_and_run=AsyncMock())


def _ev(text: str = "") -> Any:
    return SimpleNamespace(channel="web", session_id="sid:u1", user_id="u1", text=text)


def _last_send(gw: _FakeGateway) -> str:
    call: Any = gw._send.await_args_list[-1]
    result: str = call.args[2]
    return result


def _match(intent: Any, text: str) -> Any:
    m = intent.pattern.search(text)
    assert m is not None
    return m


# ── dispatcher ────────────────────────────────────────────────────


async def test_handle_intent_no_match_returns_false() -> None:
    gw: Any = _FakeGateway()
    assert await handle_intent(gw, _ev("hello there friend")) is False
    gw._send.assert_not_awaited()


async def test_handle_intent_dispatches_first_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.intents.check_price", AsyncMock(return_value="BTC $50,000"))
    gw: Any = _FakeGateway()
    assert await handle_intent(gw, _ev("what is the price of btc")) is True
    assert _last_send(gw) == "BTC $50,000"


# ── PriceIntent ───────────────────────────────────────────────────


async def test_price_intent_group1(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Monitor] = []

    async def _cp(mon: Monitor) -> str:
        captured.append(mon)
        return "ETH $3000"

    monkeypatch.setattr("raven.core.gateway.intents.check_price", _cp)
    gw: Any = _FakeGateway()
    m = _match(PriceIntent, "price of eth")
    assert await PriceIntent().handle(gw, _ev(), m) is True
    assert captured[0].target == "eth"
    assert _last_send(gw) == "ETH $3000"


async def test_price_intent_group2(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Monitor] = []

    async def _cp(mon: Monitor) -> str:
        captured.append(mon)
        return "SOL $120"

    monkeypatch.setattr("raven.core.gateway.intents.check_price", _cp)
    gw: Any = _FakeGateway()
    m = _match(PriceIntent, "sol price")
    assert await PriceIntent().handle(gw, _ev(), m) is True
    assert captured[0].target == "sol"


async def test_price_intent_group3(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Monitor] = []

    async def _cp(mon: Monitor) -> str:
        captured.append(mon)
        return "DOGE $0.1"

    monkeypatch.setattr("raven.core.gateway.intents.check_price", _cp)
    gw: Any = _FakeGateway()
    m = _match(PriceIntent, "how much is doge")
    assert await PriceIntent().handle(gw, _ev(), m) is True
    assert captured[0].target == "doge"


async def test_price_intent_empty_result_no_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.intents.check_price", AsyncMock(return_value=None))
    gw: Any = _FakeGateway()
    m = _match(PriceIntent, "price of xrp")
    assert await PriceIntent().handle(gw, _ev(), m) is True
    gw._send.assert_not_awaited()


async def test_price_intent_swallows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(mon: Monitor) -> str:
        raise RuntimeError("api down")

    monkeypatch.setattr("raven.core.gateway.intents.check_price", _boom)
    gw: Any = _FakeGateway()
    m = _match(PriceIntent, "price of ada")
    assert await PriceIntent().handle(gw, _ev(), m) is True
    gw._send.assert_not_awaited()


# ── MonitorIntent ─────────────────────────────────────────────────


async def test_monitor_intent_empty() -> None:
    gw: Any = _FakeGateway()
    gw._monitor_store.list_monitors = AsyncMock(return_value=[])
    m = _match(MonitorIntent, "how are my monitors")
    assert await MonitorIntent().handle(gw, _ev(), m) is True
    assert _last_send(gw) == "You have no monitors configured."


async def test_monitor_intent_lists() -> None:
    gw: Any = _FakeGateway()
    gw._monitor_store.list_monitors = AsyncMock(
        return_value=[
            Monitor(name="Site", type=MonitorType.HTTP, status=MonitorStatus.ACTIVE, interval_seconds=120),
            Monitor(name="Feed", type=MonitorType.RSS, status=MonitorStatus.PAUSED, interval_seconds=300),
        ]
    )
    m = _match(MonitorIntent, "list my monitors")
    assert await MonitorIntent().handle(gw, _ev(), m) is True
    out = _last_send(gw)
    assert "Your Monitors:" in out
    assert "Site [http] every 120s" in out
    assert "Feed [rss] every 300s" in out


# ── BriefingIntent ────────────────────────────────────────────────


async def test_briefing_intent_with_result() -> None:
    gw: Any = _FakeGateway()
    skill = MagicMock()
    skill.execute = AsyncMock(return_value="Here is your briefing")
    gw._get_skill = MagicMock(return_value=skill)
    m = _match(BriefingIntent, "morning briefing")
    assert await BriefingIntent().handle(gw, _ev(), m) is True
    skill.execute.assert_awaited_once_with("u1", "web")
    assert _last_send(gw) == "Here is your briefing"


async def test_briefing_intent_empty_result() -> None:
    gw: Any = _FakeGateway()
    skill = MagicMock()
    skill.execute = AsyncMock(return_value="")
    gw._get_skill = MagicMock(return_value=skill)
    m = _match(BriefingIntent, "daily summary")
    assert await BriefingIntent().handle(gw, _ev(), m) is True
    assert _last_send(gw) == "Morning briefing skill not loaded."


async def test_briefing_intent_no_skill() -> None:
    gw: Any = _FakeGateway()
    gw._get_skill = MagicMock(return_value=None)
    m = _match(BriefingIntent, "good morning")
    assert await BriefingIntent().handle(gw, _ev(), m) is True
    assert _last_send(gw) == "Morning briefing skill not loaded."


# ── TaskIntent ────────────────────────────────────────────────────


async def test_task_intent_creates_task() -> None:
    gw: Any = _FakeGateway()
    ev = _ev("remind me to call mom")
    m = _match(TaskIntent, "remind me to call mom")
    assert await TaskIntent().handle(gw, ev, m) is True
    gw.tasks.create_and_run.assert_awaited_once_with(
        goal="remind me to call mom", user_id="u1", channel="web", session_id="sid:u1"
    )


async def test_task_intent_swallows_error() -> None:
    gw: Any = _FakeGateway()
    gw.tasks.create_and_run = AsyncMock(side_effect=RuntimeError("planner down"))
    m = _match(TaskIntent, "set a reminder")
    assert await TaskIntent().handle(gw, _ev(), m) is True
