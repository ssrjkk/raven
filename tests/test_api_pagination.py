from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest


async def _seed_monitors(store: Any, n: int, prefix: str = "m") -> None:
    from raven.core.monitor.models import Monitor, MonitorStatus, MonitorType

    for i in range(n):
        m = Monitor(
            id=f"{prefix}_{i}",
            name=f"{prefix}_{i}",
            type=MonitorType.HTTP,
            target="http://example.com",
            interval_seconds=300,
            status=MonitorStatus.ACTIVE,
            conditions=[],
            notify_channels=[],
            config={"target": "http://example.com"},
        )
        await store.save_monitor(m)


async def _seed_routines(store: Any, n: int, prefix: str = "r") -> None:
    from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

    for i in range(n):
        r = Routine(
            id=f"{prefix}_{i}",
            name=f"{prefix}_{i}",
            action=RoutineAction.SEND_MESSAGE,
            trigger=RoutineTrigger.MANUAL,
            schedule="08:00",
            status=RoutineStatus.ACTIVE,
        )
        await store.save_routine(r)


async def _seed_tasks(store: Any, n: int) -> None:
    from raven.core.task_engine.models import Task, TaskStatus

    now = time.time()
    for i in range(n):
        t = Task(
            id=f"t_{i}",
            user_id="test",
            goal=f"task_{i}",
            status=TaskStatus.PENDING,
            created_at=now + i,
            updated_at=now + i,
            steps=[],
        )
        await store.save_task(t)


async def _seed_sessions(mgr: Any, n: int) -> None:
    from raven.core.coder.models import CodingSession, SessionStatus

    now = time.time()
    for i in range(n):
        s = CodingSession(
            id=f"s_{i}",
            goal=f"session_{i}",
            status=SessionStatus.ACTIVE,
            created_at=now + i,
            updated_at=now + i,
        )
        await mgr.create_session(s)


@pytest.fixture(autouse=True)
async def _reset_conns() -> None:
    pass


class TestMonitorPagination:
    @pytest.mark.asyncio
    async def test_list_with_limit(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        await _seed_monitors(store, 10)

        items = await store.list_monitors(limit=3, offset=0)
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_list_with_offset(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        await _seed_monitors(store, 10)

        page1 = await store.list_monitors(limit=5, offset=0)
        page2 = await store.list_monitors(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1[0].id != page2[0].id

    @pytest.mark.asyncio
    async def test_count(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        await _seed_monitors(store, 7)

        assert await store.count_monitors() == 7

    @pytest.mark.asyncio
    async def test_count_with_status_filter(self, tmp_path: Path) -> None:
        from raven.core.monitor.models import MonitorStatus
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        await _seed_monitors(store, 5)
        await store.update_status("m_0", MonitorStatus.PAUSED)

        assert await store.count_monitors(status="active") == 4
        assert await store.count_monitors(status="paused") == 1

    @pytest.mark.asyncio
    async def test_limit_capped_by_store_default(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        await _seed_monitors(store, 200)

        items = await store.list_monitors(limit=999999, offset=0)
        assert len(items) <= 1000


class TestRoutinePagination:
    @pytest.mark.asyncio
    async def test_list_with_limit(self, tmp_path: Path) -> None:
        from raven.core.routine.store import RoutineStore

        db = tmp_path / "routines.db"
        store = RoutineStore(db)
        await _seed_routines(store, 10)

        items = await store.list_routines(limit=3, offset=0)
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_count(self, tmp_path: Path) -> None:
        from raven.core.routine.store import RoutineStore

        db = tmp_path / "routines.db"
        store = RoutineStore(db)
        await _seed_routines(store, 7)

        assert await store.count_routines() == 7


class TestTaskPagination:
    @pytest.mark.asyncio
    async def test_list_with_limit(self, tmp_path: Path) -> None:
        from raven.core.task_engine.store import TaskStore

        db = tmp_path / "tasks.db"
        store = TaskStore(db)
        await _seed_tasks(store, 10)

        items = await store.list_tasks(limit=3, offset=0)
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_count(self, tmp_path: Path) -> None:
        from raven.core.task_engine.store import TaskStore

        db = tmp_path / "tasks.db"
        store = TaskStore(db)
        await _seed_tasks(store, 7)

        assert await store.count_tasks() == 7


class TestCodeSessionPagination:
    @pytest.mark.asyncio
    async def test_list_with_limit_and_offset(self, tmp_path: Path) -> None:
        from raven.core.coder.session import CodingSessionManager

        db = tmp_path / "sessions.db"
        mgr = CodingSessionManager(db)
        await _seed_sessions(mgr, 10)

        items = await mgr.list_sessions(limit=3, offset=0)
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_list_with_offset_skips_first(self, tmp_path: Path) -> None:
        from raven.core.coder.session import CodingSessionManager

        db = tmp_path / "sessions.db"
        mgr = CodingSessionManager(db)
        await _seed_sessions(mgr, 5)

        items = await mgr.list_sessions(limit=3, offset=2)
        assert len(items) == 3
        assert items[0].id == "s_2"

    @pytest.mark.asyncio
    async def test_count(self, tmp_path: Path) -> None:
        from raven.core.coder.session import CodingSessionManager

        db = tmp_path / "sessions.db"
        mgr = CodingSessionManager(db)
        await _seed_sessions(mgr, 7)

        assert await mgr.count_sessions() == 7

    @pytest.mark.asyncio
    async def test_count_by_user(self, tmp_path: Path) -> None:
        from raven.core.coder.models import CodingSession
        from raven.core.coder.session import CodingSessionManager

        db = tmp_path / "sessions.db"
        mgr = CodingSessionManager(db)
        await _seed_sessions(mgr, 3)
        s = CodingSession(id="u_s", goal="u", user_id="other_user")
        await mgr.create_session(s)

        assert await mgr.count_sessions() == 4
