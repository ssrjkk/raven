from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.auth import Permission
from raven.core.gateway.commands.monitor import MonitorCommand
from raven.core.monitor.models import CheckResult, Monitor, MonitorStatus, MonitorType


class _FakeGateway:
    def __init__(self) -> None:
        self._send = AsyncMock()
        self._check_permission = MagicMock(return_value=True)
        self._monitor_store = _FakeStore()


class _FakeStore:
    def __init__(self) -> None:
        self.monitors: list[Monitor] = []
        self.saved: list[Monitor] = []
        self.deleted: list[str] = []
        self.status_updates: list[tuple[str, MonitorStatus]] = []
        self.load_result: Monitor | None = None

    async def list_monitors(self, user_id: str = "") -> list[Monitor]:
        return self.monitors

    async def save_monitor(self, monitor: Monitor) -> None:
        self.saved.append(monitor)

    async def load_monitor(self, monitor_id: str) -> Monitor | None:
        return self.load_result

    async def delete_monitor(self, monitor_id: str) -> None:
        self.deleted.append(monitor_id)

    async def update_status(self, monitor_id: str, status: MonitorStatus) -> None:
        self.status_updates.append((monitor_id, status))


def _ctx(args: list[str] | None = None) -> Any:
    return SimpleNamespace(
        args=args or [],
        user={"id": "u1"},
        event=SimpleNamespace(channel="web", session_id="sid-1", user_id="u1"),
    )


def _sent(gw: _FakeGateway) -> tuple[str, str, str]:
    call = gw._send.await_args_list[-1]
    return call.args[0], call.args[1], call.args[2]


@pytest.fixture(autouse=True)
def _no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("raven.core.gateway.commands.monitor.get_policy_for_channel", lambda ch: None)


def test_monitor_name_and_description() -> None:
    cmd = MonitorCommand(_FakeGateway())
    assert cmd.name == "monitor"
    assert cmd.description == "Monitor management"


async def test_monitor_policy_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.commands.monitor.check_tool_allowed",
        lambda policy, action, ch: (False, "blocked"),
    )
    monkeypatch.setattr(
        "raven.core.gateway.commands.monitor.get_policy_for_channel", lambda ch: object()
    )
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Access denied: blocked"


async def test_monitor_read_permission_denied() -> None:
    gw = _FakeGateway()
    gw._check_permission = MagicMock(return_value=False)
    assert await MonitorCommand(gw).execute(_ctx(args=["list"])) is True
    assert _sent(gw)[2] == "Access denied: insufficient permissions"


async def test_monitor_write_permission_denied() -> None:
    gw = _FakeGateway()
    gw._check_permission = MagicMock(
        side_effect=lambda user, perm: perm is not Permission.MONITOR_WRITE
    )
    assert await MonitorCommand(gw).execute(_ctx(args=["add", "http", "https://x"])) is True
    assert _sent(gw)[2] == "Access denied: insufficient permissions"


async def test_monitor_list_empty() -> None:
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx(args=["list"])) is True
    assert _sent(gw)[2] == "No monitors configured."


async def test_monitor_list_with_entries() -> None:
    gw = _FakeGateway()
    gw._monitor_store.monitors = [
        Monitor(name="Site", type=MonitorType.HTTP, target="https://x", status=MonitorStatus.ACTIVE,
                last_check=CheckResult(status="up")),
        Monitor(name="Feed", type=MonitorType.RSS, target="https://y", status=MonitorStatus.PAUSED),
        Monitor(name="Broken", type=MonitorType.FILE, target="/p", status=MonitorStatus.ERROR),
    ]
    assert await MonitorCommand(gw).execute(_ctx(args=["list"])) is True
    # the "list" branch sends the list first, then falls through to the help block
    out = gw._send.await_args_list[0].args[2]
    assert "Your Monitors:" in out
    assert "🟢" in out and "⏸" in out and "🔴" in out
    assert "Site [http] every 300s ✅" in out
    assert "Feed [rss]" in out


async def test_monitor_list_shows_down_status() -> None:
    gw = _FakeGateway()
    gw._monitor_store.monitors = [
        Monitor(name="Site", type=MonitorType.HTTP, status=MonitorStatus.ACTIVE,
                last_check=CheckResult(status="down")),
    ]
    assert await MonitorCommand(gw).execute(_ctx(args=["list"])) is True
    assert "❌" in gw._send.await_args_list[0].args[2]


async def test_monitor_add_missing_args() -> None:
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx(args=["add", "http"])) is True
    assert "Usage: /monitor add" in _sent(gw)[2]


async def test_monitor_add_unknown_type() -> None:
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx(args=["add", "bogus", "target"])) is True
    assert _sent(gw)[2] == "Unknown type: bogus"


async def test_monitor_add_success() -> None:
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx(args=["add", "http", "https://ex.com", "My", "Site"])) is True
    saved = gw._monitor_store.saved
    assert len(saved) == 1
    assert saved[0].name == "My Site"
    assert saved[0].type is MonitorType.HTTP
    assert saved[0].target == "https://ex.com"
    out = _sent(gw)[2]
    assert "Monitor 'My Site'" in out
    assert "added. Checks every 5min." in out


async def test_monitor_add_default_name() -> None:
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx(args=["add", "price", "BTC"])) is True
    assert gw._monitor_store.saved[0].name == "price:BTC"


async def test_monitor_remove_not_found() -> None:
    gw = _FakeGateway()
    gw._monitor_store.load_result = None
    assert await MonitorCommand(gw).execute(_ctx(args=["remove", "abc"])) is True
    assert _sent(gw)[2] == "Monitor not found: abc"


async def test_monitor_remove_success() -> None:
    gw = _FakeGateway()
    gw._monitor_store.load_result = Monitor(id="abcd1234", name="Site")
    assert await MonitorCommand(gw).execute(_ctx(args=["remove", "abcd1234"])) is True
    assert gw._monitor_store.deleted == ["abcd1234"]
    assert _sent(gw)[2] == "🗑 Monitor 'Site' removed."


async def test_monitor_pause_not_found() -> None:
    gw = _FakeGateway()
    gw._monitor_store.load_result = None
    assert await MonitorCommand(gw).execute(_ctx(args=["pause", "zz"])) is True
    assert _sent(gw)[2] == "Monitor not found: zz"


async def test_monitor_pause_success() -> None:
    gw = _FakeGateway()
    gw._monitor_store.load_result = Monitor(id="m1", name="Site")
    assert await MonitorCommand(gw).execute(_ctx(args=["pause", "m1"])) is True
    assert gw._monitor_store.status_updates == [("m1", MonitorStatus.PAUSED)]
    assert _sent(gw)[2] == "⏸ Monitor 'Site' paused."


async def test_monitor_resume_not_found() -> None:
    gw = _FakeGateway()
    gw._monitor_store.load_result = None
    assert await MonitorCommand(gw).execute(_ctx(args=["resume", "zz"])) is True
    assert _sent(gw)[2] == "Monitor not found: zz"


async def test_monitor_resume_success() -> None:
    gw = _FakeGateway()
    gw._monitor_store.load_result = Monitor(id="m1", name="Site")
    assert await MonitorCommand(gw).execute(_ctx(args=["resume", "m1"])) is True
    assert gw._monitor_store.status_updates == [("m1", MonitorStatus.ACTIVE)]
    assert _sent(gw)[2] == "▶️ Monitor 'Site' resumed."


async def test_monitor_help_default() -> None:
    gw = _FakeGateway()
    assert await MonitorCommand(gw).execute(_ctx()) is True
    out = _sent(gw)[2]
    assert "Monitor commands:" in out
    assert "/monitor add http <url>" in out
