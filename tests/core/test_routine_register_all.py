from __future__ import annotations

from typing import Any

import pytest

from raven.core.routine.models import Routine, RoutineAction
from raven.routines import register_all
from raven.routines.actions import check_email, execute_briefing, organize_files
from raven.routines.register_all import register_all_routines


class _FakeEngine:
    def __init__(self, existing: list[Routine]) -> None:
        self.registered: dict[str, Any] = {}
        self.added: list[Routine] = []
        self._existing = existing

    def register_handler(self, name: str, handler: Any) -> None:
        self.registered[name] = handler

    async def list_routines(self) -> list[Routine]:
        return self._existing

    async def add_routine(self, routine: Routine) -> None:
        self.added.append(routine)


@pytest.mark.asyncio
async def test_registers_handlers_and_seeds_defaults() -> None:
    engine = _FakeEngine(existing=[])
    await register_all_routines(engine)  # type: ignore[arg-type]
    assert engine.registered[RoutineAction.SEND_BRIEFING.value] is execute_briefing
    assert engine.registered[RoutineAction.CHECK_EMAIL.value] is check_email
    assert engine.registered[RoutineAction.ORGANIZE_FILES.value] is organize_files
    assert len(engine.added) == 3
    names = {r.name for r in engine.added}
    assert names == {"Morning Briefing", "Email Check (Hourly)", "File Organizer (Daily)"}
    by_name = {r.name: r for r in engine.added}
    assert by_name["Email Check (Hourly)"].config["provider"] == "imap"
    assert by_name["File Organizer (Daily)"].config["dry_run"] is True


@pytest.mark.asyncio
async def test_skips_already_present_routines() -> None:
    existing = [
        Routine(name="Morning Briefing"),
        Routine(name="Email Check (Hourly)"),
        Routine(name="File Organizer (Daily)"),
    ]
    engine = _FakeEngine(existing=existing)
    await register_all_routines(engine)  # type: ignore[arg-type]
    assert engine.added == []  # nothing new seeded
    assert len(engine.registered) == 3


def test_module_exports() -> None:
    assert register_all.register_all_routines is register_all_routines
