from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
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


class TestValidateSchedule:
    def test_valid_interval(self) -> None:
        assert RoutineEngine.validate_schedule("3600") is None

    def test_zero_interval_rejected(self) -> None:
        assert RoutineEngine.validate_schedule("0") is not None

    def test_negative_interval_rejected(self) -> None:
        assert RoutineEngine.validate_schedule("-5") is not None

    def test_float_schedule_rejected(self) -> None:
        assert RoutineEngine.validate_schedule("5.5") is not None

    def test_valid_hhmm(self) -> None:
        assert RoutineEngine.validate_schedule("14:30") is None

    def test_bad_hhmm_rejected(self) -> None:
        assert RoutineEngine.validate_schedule("25:99") is not None

    def test_valid_cron(self) -> None:
        assert RoutineEngine.validate_schedule("*/5 * * * *") is None

    def test_short_cron_rejected(self) -> None:
        assert RoutineEngine.validate_schedule("*/5 * *") is not None


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


class TestRoutineScheduling:
    def test_next_run_future_today(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("08:00", now)
        assert nxt == datetime(2026, 1, 15, 8, 0, tzinfo=UTC)

    def test_next_run_passed_today_rolls_to_tomorrow(self):
        now = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("08:00", now)
        assert nxt == datetime(2026, 1, 16, 8, 0, tzinfo=UTC)

    def test_next_run_month_end_does_not_crash(self):
        now = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("08:00", now)
        assert nxt == datetime(2026, 2, 1, 8, 0, tzinfo=UTC)

    def test_next_run_exact_time_is_tomorrow(self):
        now = datetime(2026, 1, 31, 8, 0, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("08:00", now)
        assert nxt == datetime(2026, 2, 1, 8, 0, tzinfo=UTC)

    def test_next_run_year_end_rolls_to_next_year(self):
        now = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("08:00", now)
        assert nxt == datetime(2027, 1, 1, 8, 0, tzinfo=UTC)

    def test_delay_until_positive(self):
        now = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
        delay = RoutineEngine._delay_until("08:00", now)
        assert 23 * 3600 <= delay <= 24 * 3600

    def test_default_schedule_parts(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        single = RoutineEngine._next_run_time("10", now)
        assert single is not None and single.hour == 10
        empty = RoutineEngine._next_run_time("", now)
        assert empty is not None and empty.hour == 8

    def test_cron_every_5_minutes(self):
        now = datetime(2026, 1, 15, 7, 2, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("*/5 * * * *", now)
        assert nxt == datetime(2026, 1, 15, 7, 5, tzinfo=UTC)

    def test_cron_daily_time(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("30 8 * * *", now)
        assert nxt == datetime(2026, 1, 15, 8, 30, tzinfo=UTC)

    def test_cron_weekday(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        assert now.weekday() == 3
        nxt = RoutineEngine._next_run_time("0 9 31 * 1", now)
        assert nxt == datetime(2026, 1, 19, 9, 0, tzinfo=UTC)
        assert nxt.weekday() == 0

    def test_cron_sunday_alias_7(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("0 0 1 * 7", now)
        assert nxt == datetime(2026, 1, 18, 0, 0, tzinfo=UTC)
        assert nxt.weekday() == 6

    def test_cron_wildcard_dom_matches_every_day(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("0 0 * * 7", now)
        assert nxt == datetime(2026, 1, 16, 0, 0, tzinfo=UTC)

    def test_cron_range_with_step(self):
        now = datetime(2026, 1, 15, 17, 59, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("*/15 9-17 * * *", now)
        assert nxt == datetime(2026, 1, 16, 9, 0, tzinfo=UTC)

    def test_cron_first_of_month_union_semantics(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        nxt = RoutineEngine._next_run_time("0 0 1 * *", now)
        assert nxt == datetime(2026, 1, 16, 0, 0, tzinfo=UTC)

    def test_cron_invalid_schedule_returns_none(self):
        now = datetime(2026, 1, 15, 7, 0, tzinfo=UTC)
        assert RoutineEngine._next_run_time("not a cron at all", now) is None
        assert RoutineEngine._next_run_time("* * * *", now) is None
        assert RoutineEngine._delay_until("bad schedule", now) == -1.0
        assert RoutineEngine._delay_until("a:b:c", now) == -1.0


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


class TestRoutineEngineLoop:
    async def test_interval_loop_sends_message_via_gateway(self, store: RoutineStore):
        engine = RoutineEngine(store)
        gw = SimpleNamespace(_send=AsyncMock(return_value=None))
        engine._gateway_ref = gw
        r = Routine(
            name="reminder",
            channel="mock",
            user_id="u1",
            action=RoutineAction.SEND_MESSAGE,
            trigger=RoutineTrigger.INTERVAL,
            schedule="1",
            config={"text": "hello world"},
        )
        await store.save_routine(r)
        try:
            await engine.start()
            for _ in range(50):
                if gw._send.await_count > 0:
                    break
                await asyncio.sleep(0.1)
            gw._send.assert_awaited_once()
            call_args = gw._send.await_args.args
            assert call_args[0] == "mock"
            assert call_args[2] == "hello world"
            logs = await store.get_logs(r.id)
            assert len(logs) >= 1
            assert logs[0].status == "success"
            loaded = await store.load_routine(r.id)
            assert loaded is not None
            assert loaded.last_run_status == "success"
        finally:
            await engine.stop()

    async def test_scheduled_loop_waits_and_executes(self, store: RoutineStore):
        engine = RoutineEngine(store)
        gw = SimpleNamespace(_send=AsyncMock(return_value=None))
        engine._gateway_ref = gw
        r = Routine(
            name="brief",
            channel="mock",
            user_id="u1",
            action=RoutineAction.SEND_BRIEFING,
            trigger=RoutineTrigger.SCHEDULED,
            schedule="08:00",
        )
        await store.save_routine(r)
        try:
            engine._schedule_item(r)
            loop_task = engine._tasks[r.id]
            # scheduled for the next 08:00 — must NOT fire within 0.5s
            await asyncio.sleep(0.5)
            gw._send.assert_not_awaited()
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
        finally:
            await engine.stop()

    async def test_cron_loop_fires_at_match(self, store: RoutineStore, monkeypatch: pytest.MonkeyPatch):
        engine = RoutineEngine(store)
        gw = SimpleNamespace(_send=AsyncMock(return_value=None))
        engine._gateway_ref = gw
        monkeypatch.setattr(RoutineEngine, "_delay_until", classmethod(lambda cls, schedule, now=None: 0.0))
        r = Routine(
            name="cron",
            channel="mock",
            user_id="u1",
            action=RoutineAction.SEND_BRIEFING,
            trigger=RoutineTrigger.SCHEDULED,
            schedule="*/5 * * * *",
        )
        await store.save_routine(r)
        try:
            await engine.start()
            for _ in range(50):
                if gw._send.await_count > 0:
                    break
                await asyncio.sleep(0.1)
            gw._send.assert_awaited()
            logs = await store.get_logs(r.id)
            assert any(log.status == "success" for log in logs)
        finally:
            await engine.stop()

    async def test_invalid_interval_schedule_loop_survives(self, store: RoutineStore):
        engine = RoutineEngine(store)
        r = Routine(
            name="broken",
            action=RoutineAction.SEND_MESSAGE,
            trigger=RoutineTrigger.INTERVAL,
            schedule="not-a-number",
        )
        await store.save_routine(r)
        try:
            await engine.start()
            await asyncio.sleep(0.3)
            task = engine._tasks.get(r.id)
            assert task is not None and not task.done()
        finally:
            await engine.stop()


class TestRoutineActions:
    async def test_organize_files_uses_configured_workspace(
        self, tmp_path: Path, store: RoutineStore, monkeypatch: pytest.MonkeyPatch
    ):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "notes.txt").write_text("a")
        (workspace / "main.py").write_text("print(1)")
        (workspace / "archive.zip").write_bytes(b"\x00")
        engine = RoutineEngine(store)
        r = Routine(name="org", action=RoutineAction.ORGANIZE_FILES, trigger=RoutineTrigger.MANUAL)
        engine._gateway_ref = SimpleNamespace(_send=AsyncMock(return_value=None))
        monkeypatch.setattr(
            "raven.core.config.get_settings",
            lambda: SimpleNamespace(resolved_workspace=workspace),
        )
        result = await engine._execute_file_organization(r)
        assert "2" in result
        assert (workspace / "text" / "notes.txt").exists()
        assert (workspace / "code" / "main.py").exists()
        assert (workspace / "archive.zip").exists()
