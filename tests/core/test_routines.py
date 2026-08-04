from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raven.core.routine.engine import RoutineEngine
from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus, RoutineTrigger
from raven.core.routine.store import RoutineStore


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "routines.db")


@pytest.fixture
async def store(db_path: str):
    s = RoutineStore(db_path)
    yield s
    await s.close()


@pytest.fixture
def routine() -> Routine:
    return Routine(
        name="test-briefing",
        action=RoutineAction.SEND_BRIEFING,
        trigger=RoutineTrigger.INTERVAL,
        schedule="3600",
        status=RoutineStatus.ACTIVE,
    )


class TestRoutineStore:
    @pytest.mark.asyncio
    async def test_save_and_load(self, store: RoutineStore, routine: Routine):
        await store.save_routine(routine)
        loaded = await store.load_routine(routine.id)
        assert loaded is not None
        assert loaded.name == "test-briefing"
        assert loaded.action == RoutineAction.SEND_BRIEFING

    @pytest.mark.asyncio
    async def test_list_active(self, store: RoutineStore):
        a = Routine(name="active-r", action=RoutineAction.SEND_MESSAGE, trigger=RoutineTrigger.MANUAL)
        b = Routine(
            name="paused-r",
            action=RoutineAction.SEND_MESSAGE,
            trigger=RoutineTrigger.MANUAL,
            status=RoutineStatus.PAUSED,
        )
        await store.save_routine(a)
        await store.save_routine(b)
        active = await store.list_active()
        assert len(active) == 1
        assert active[0].id == a.id

    @pytest.mark.asyncio
    async def test_update_status(self, store: RoutineStore, routine: Routine):
        await store.save_routine(routine)
        await store.update_status(routine.id, RoutineStatus.PAUSED)
        loaded = await store.load_routine(routine.id)
        assert loaded is not None
        assert loaded.status == RoutineStatus.PAUSED

    @pytest.mark.asyncio
    async def test_update_last_run(self, store: RoutineStore, routine: Routine):
        await store.save_routine(routine)
        await store.update_last_run(routine.id, "success")
        loaded = await store.load_routine(routine.id)
        assert loaded is not None
        assert loaded.last_run_status == "success"
        assert loaded.last_run_at is not None

    @pytest.mark.asyncio
    async def test_delete(self, store: RoutineStore, routine: Routine):
        await store.save_routine(routine)
        await store.delete_routine(routine.id)
        loaded = await store.load_routine(routine.id)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_routines(self, store: RoutineStore):
        a = Routine(name="r1", action=RoutineAction.CHECK_EMAIL, trigger=RoutineTrigger.MANUAL)
        b = Routine(name="r2", action=RoutineAction.ORGANIZE_FILES, trigger=RoutineTrigger.MANUAL)
        await store.save_routine(a)
        await store.save_routine(b)
        all_r = await store.list_routines()
        assert len(all_r) == 2

    @pytest.mark.asyncio
    async def test_save_and_get_logs(self, store: RoutineStore, routine: Routine):
        await store.save_routine(routine)
        log = RoutineLog(routine_id=routine.id, status="success", message="done", duration_ms=100.0)
        await store.save_log(log)
        logs = await store.get_logs(routine.id)
        assert len(logs) == 1
        assert logs[0].status == "success"


class TestRoutineEngine:
    async def test_start_stop(self, store: RoutineStore):
        engine = RoutineEngine(store)
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

    async def test_add_routine_interval(self, store: RoutineStore):
        handler = AsyncMock(return_value="briefing sent")
        engine = RoutineEngine(store)
        engine.register_handler("send_briefing", handler)
        await engine.start()

        r = Routine(
            name="briefing",
            action=RoutineAction.SEND_BRIEFING,
            trigger=RoutineTrigger.INTERVAL,
            schedule="3600",
        )
        await engine.add_routine(r)
        assert r.id in engine._tasks

        await engine.stop()

    async def test_pause_resume(self, store: RoutineStore):
        handler = AsyncMock(return_value="ok")
        engine = RoutineEngine(store)
        engine.register_handler("send_message", handler)
        await engine.start()

        r = Routine(
            name="msg",
            action=RoutineAction.SEND_MESSAGE,
            trigger=RoutineTrigger.INTERVAL,
            schedule="3600",
        )
        await engine.add_routine(r)
        assert r.id in engine._tasks

        paused = await engine.pause_routine(r.id)
        assert paused is True
        assert r.id not in engine._tasks
        loaded = await store.load_routine(r.id)
        assert loaded is not None
        assert loaded.status == RoutineStatus.PAUSED

        resumed = await engine.resume_routine(r.id)
        assert resumed is True
        assert r.id in engine._tasks

        await engine.stop()

    async def test_remove_routine(self, store: RoutineStore):
        handler = AsyncMock(return_value="ok")
        engine = RoutineEngine(store)
        engine.register_handler("send_message", handler)
        await engine.start()

        r = Routine(
            name="test",
            action=RoutineAction.SEND_MESSAGE,
            trigger=RoutineTrigger.INTERVAL,
            schedule="3600",
        )
        await engine.add_routine(r)
        assert r.id in engine._tasks

        await engine.remove_routine(r.id)
        loaded = await store.load_routine(r.id)
        assert loaded is None

        await engine.stop()

    async def test_execute_routine_creates_log(self, store: RoutineStore):
        handler = AsyncMock(return_value="executed successfully")
        engine = RoutineEngine(store)
        engine.register_handler("send_briefing", handler)
        await engine.start()

        r = Routine(
            name="briefing",
            action=RoutineAction.SEND_BRIEFING,
            trigger=RoutineTrigger.INTERVAL,
            schedule="3600",
        )
        await store.save_routine(r)

        await engine._execute_routine(r)
        logs = await store.get_logs(r.id)
        assert len(logs) == 1
        assert logs[0].status == "success"

        loaded = await store.load_routine(r.id)
        assert loaded is not None
        assert loaded.last_run_status == "success"

        await engine.stop()

    async def test_execute_routine_failure(self, store: RoutineStore):
        handler = AsyncMock(side_effect=ValueError("simulated failure"))
        engine = RoutineEngine(store)
        engine.register_handler("send_briefing", handler)
        await engine.start()

        r = Routine(
            name="briefing",
            action=RoutineAction.SEND_BRIEFING,
            trigger=RoutineTrigger.INTERVAL,
            schedule="3600",
        )
        await store.save_routine(r)

        await engine._execute_routine(r)
        logs = await store.get_logs(r.id)
        assert len(logs) == 1
        assert logs[0].status == "error"
        assert "simulated failure" in logs[0].message

        await engine.stop()
