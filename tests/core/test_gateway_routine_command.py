from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.auth import Permission
from raven.core.gateway.commands.routine import RoutineCommand
from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger


class _FakeGateway:
    def __init__(self) -> None:
        self._send = AsyncMock()
        self._check_permission = MagicMock(return_value=True)
        self._routine_store = _FakeStore()


class _FakeStore:
    def __init__(self) -> None:
        self.routines: list[Routine] = []
        self.saved: list[Routine] = []
        self.deleted: list[str] = []
        self.status_updates: list[tuple[str, RoutineStatus]] = []
        self.load_result: Routine | None = None

    async def list_routines(self, user_id: str = "") -> list[Routine]:
        return self.routines

    async def save_routine(self, routine: Routine) -> None:
        self.saved.append(routine)

    async def load_routine(self, routine_id: str) -> Routine | None:
        return self.load_result

    async def delete_routine(self, routine_id: str) -> None:
        self.deleted.append(routine_id)

    async def update_status(self, routine_id: str, status: RoutineStatus) -> None:
        self.status_updates.append((routine_id, status))


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
    monkeypatch.setattr("raven.core.gateway.commands.routine.get_policy_for_channel", lambda ch: None)


@pytest.fixture(autouse=True)
def _valid_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.routine.engine.RoutineEngine.validate_schedule", staticmethod(lambda s: None)
    )


def test_routine_name_and_description() -> None:
    cmd = RoutineCommand(_FakeGateway())
    assert cmd.name == "routine"
    assert cmd.description == "Routine management"


async def test_routine_policy_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.gateway.commands.routine.check_tool_allowed",
        lambda policy, action, ch: (False, "blocked"),
    )
    monkeypatch.setattr(
        "raven.core.gateway.commands.routine.get_policy_for_channel", lambda ch: object()
    )
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx()) is True
    assert _sent(gw)[2] == "Access denied: blocked"


async def test_routine_read_permission_denied() -> None:
    gw = _FakeGateway()
    gw._check_permission = MagicMock(return_value=False)
    assert await RoutineCommand(gw).execute(_ctx(args=["list"])) is True
    assert _sent(gw)[2] == "Access denied: insufficient permissions"


async def test_routine_write_permission_denied() -> None:
    gw = _FakeGateway()
    gw._check_permission = MagicMock(side_effect=lambda user, perm: perm is not Permission.ROUTINE_WRITE)
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "send_briefing", "08:00"])) is True
    assert _sent(gw)[2] == "Access denied: insufficient permissions"


async def test_routine_list_empty() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["list"])) is True
    assert _sent(gw)[2] == "No routines configured."


async def test_routine_list_with_entries() -> None:
    gw = _FakeGateway()
    gw._routine_store.routines = [
        Routine(name="Morning", action=RoutineAction.SEND_BRIEFING, schedule="08:00",
                status=RoutineStatus.ACTIVE, last_run_status="ok"),
        Routine(name="Paused one", action=RoutineAction.CHECK_EMAIL, schedule="300",
                status=RoutineStatus.PAUSED),
    ]
    assert await RoutineCommand(gw).execute(_ctx(args=["list"])) is True
    out = gw._send.await_args_list[0].args[2]
    assert "Your Routines:" in out
    assert "🟢" in out and "⏸" in out
    assert "Morning [send_briefing] 08:00 last: ok" in out


async def test_routine_add_missing_args() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "send_briefing"])) is True
    assert "Usage: /routine add" in _sent(gw)[2]


async def test_routine_add_unknown_action() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "bogus", "08:00"])) is True
    assert _sent(gw)[2] == "Unknown action: bogus"


async def test_routine_add_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "raven.core.routine.engine.RoutineEngine.validate_schedule",
        staticmethod(lambda s: "bad schedule"),
    )
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "send_briefing", "nonsense"])) is True
    assert _sent(gw)[2] == "❌ bad schedule"


async def test_routine_add_scheduled() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "send_briefing", "08:00", "My", "Brief"])) is True
    saved = gw._routine_store.saved[0]
    assert saved.name == "My Brief"
    assert saved.action is RoutineAction.SEND_BRIEFING
    assert saved.trigger is RoutineTrigger.SCHEDULED
    assert saved.schedule == "08:00"
    out = _sent(gw)[2]
    assert "Routine 'My Brief'" in out
    assert "scheduled: 08:00" in out


async def test_routine_add_interval() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "check_email", "300"])) is True
    saved = gw._routine_store.saved[0]
    assert saved.trigger is RoutineTrigger.INTERVAL
    assert saved.name == "check_email@300"


async def test_routine_add_cron_five_fields() -> None:
    gw = _FakeGateway()
    ctx = _ctx(args=["add", "organize_files", "0", "8", "*", "*", "*"])
    assert await RoutineCommand(gw).execute(ctx) is True
    saved = gw._routine_store.saved[0]
    assert saved.schedule == "0 8 * * *"
    assert saved.name == "organize_files@0 8 * * *"
    assert saved.trigger is RoutineTrigger.SCHEDULED


async def test_routine_add_non_int_non_colon_is_scheduled() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx(args=["add", "send_message", "daily"])) is True
    saved = gw._routine_store.saved[0]
    assert saved.trigger is RoutineTrigger.SCHEDULED
    assert saved.schedule == "daily"


async def test_routine_remove_not_found() -> None:
    gw = _FakeGateway()
    gw._routine_store.load_result = None
    assert await RoutineCommand(gw).execute(_ctx(args=["remove", "abc"])) is True
    assert _sent(gw)[2] == "Routine not found: abc"


async def test_routine_remove_success() -> None:
    gw = _FakeGateway()
    gw._routine_store.load_result = Routine(id="abcd1234", name="Morning")
    assert await RoutineCommand(gw).execute(_ctx(args=["remove", "abcd1234"])) is True
    assert gw._routine_store.deleted == ["abcd1234"]
    assert _sent(gw)[2] == "🗑 Routine 'Morning' removed."


async def test_routine_pause_not_found() -> None:
    gw = _FakeGateway()
    gw._routine_store.load_result = None
    assert await RoutineCommand(gw).execute(_ctx(args=["pause", "zz"])) is True
    assert _sent(gw)[2] == "Routine not found: zz"


async def test_routine_pause_success() -> None:
    gw = _FakeGateway()
    gw._routine_store.load_result = Routine(id="r1", name="Morning")
    assert await RoutineCommand(gw).execute(_ctx(args=["pause", "r1"])) is True
    assert gw._routine_store.status_updates == [("r1", RoutineStatus.PAUSED)]
    assert _sent(gw)[2] == "⏸ Routine 'Morning' paused."


async def test_routine_resume_not_found() -> None:
    gw = _FakeGateway()
    gw._routine_store.load_result = None
    assert await RoutineCommand(gw).execute(_ctx(args=["resume", "zz"])) is True
    assert _sent(gw)[2] == "Routine not found: zz"


async def test_routine_resume_success() -> None:
    gw = _FakeGateway()
    gw._routine_store.load_result = Routine(id="r1", name="Morning")
    assert await RoutineCommand(gw).execute(_ctx(args=["resume", "r1"])) is True
    assert gw._routine_store.status_updates == [("r1", RoutineStatus.ACTIVE)]
    assert _sent(gw)[2] == "▶️ Routine 'Morning' resumed."


async def test_routine_help_default() -> None:
    gw = _FakeGateway()
    assert await RoutineCommand(gw).execute(_ctx()) is True
    out = _sent(gw)[2]
    assert "Routine commands:" in out
    assert "/routine add <action> <schedule> [name]" in out
