from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest


def _seed_monitors(store: Any, n: int, prefix: str = "m") -> None:
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
        store.save_monitor(m)


def _seed_routines(store: Any, n: int, prefix: str = "r") -> None:
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
        store.save_routine(r)


def _seed_tasks(store: Any, n: int) -> None:
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
        store.save_task(t)


def _seed_sessions(mgr: Any, n: int) -> None:
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
        mgr.create_session(s)


@pytest.fixture(autouse=True)
def _reset_conns() -> None:
    from raven.core.monitor.store import close_conn
    from raven.core.task_engine.store import _close_all_conns

    close_conn()
    _close_all_conns()
    # coder/session.py has no close; delete thread-local directly
    import raven.core.coder.session as cs

    if hasattr(cs._local, "conn") and cs._local.conn is not None:
        cs._local.conn.close()
        cs._local.conn = None
    # routine/store.py has no close either
    import raven.core.routine.store as rs

    if hasattr(rs._local, "conn") and rs._local.conn is not None:
        rs._local.conn.close()
        rs._local.conn = None


class TestMonitorPagination:
    def test_list_with_limit(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        _seed_monitors(store, 10)

        items = store.list_monitors(limit=3, offset=0)
        assert len(items) == 3

    def test_list_with_offset(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        _seed_monitors(store, 10)

        page1 = store.list_monitors(limit=5, offset=0)
        page2 = store.list_monitors(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1[0].id != page2[0].id

    def test_count(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        _seed_monitors(store, 7)

        assert store.count_monitors() == 7

    def test_count_with_status_filter(self, tmp_path: Path) -> None:
        from raven.core.monitor.models import MonitorStatus
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        _seed_monitors(store, 5)
        store.update_status("m_0", MonitorStatus.PAUSED)

        assert store.count_monitors(status="active") == 4
        assert store.count_monitors(status="paused") == 1

    def test_limit_capped_by_store_default(self, tmp_path: Path) -> None:
        from raven.core.monitor.store import MonitorStore

        db = tmp_path / "monitors.db"
        store = MonitorStore(db)
        _seed_monitors(store, 200)

        items = store.list_monitors(limit=999999, offset=0)
        assert len(items) <= 1000


class TestRoutinePagination:
    def test_list_with_limit(self, tmp_path: Path) -> None:
        from raven.core.routine.store import RoutineStore

        db = tmp_path / "routines.db"
        store = RoutineStore(db)
        _seed_routines(store, 10)

        items = store.list_routines(limit=3, offset=0)
        assert len(items) == 3

    def test_count(self, tmp_path: Path) -> None:
        from raven.core.routine.store import RoutineStore

        db = tmp_path / "routines.db"
        store = RoutineStore(db)
        _seed_routines(store, 7)

        assert store.count_routines() == 7


class TestTaskPagination:
    def test_list_with_limit(self, tmp_path: Path) -> None:
        from raven.core.task_engine.store import TaskStore

        db = tmp_path / "tasks.db"
        store = TaskStore(db)
        _seed_tasks(store, 10)

        items = store.list_tasks(limit=3, offset=0)
        assert len(items) == 3

    def test_count(self, tmp_path: Path) -> None:
        from raven.core.task_engine.store import TaskStore

        db = tmp_path / "tasks.db"
        store = TaskStore(db)
        _seed_tasks(store, 7)

        assert store.count_tasks() == 7


class TestCodeSessionPagination:
    def test_list_with_limit_and_offset(self, tmp_path: Path) -> None:
        from raven.core.coder.session import CodingSessionManager

        db = tmp_path / "sessions.db"
        mgr = CodingSessionManager(db)
        _seed_sessions(mgr, 10)

        page1 = mgr.list_sessions(limit=4, offset=0)
        page2 = mgr.list_sessions(limit=4, offset=4)
        assert len(page1) == 4
        assert len(page2) == 4

    def test_count(self, tmp_path: Path) -> None:
        from raven.core.coder.session import CodingSessionManager

        db = tmp_path / "sessions.db"
        mgr = CodingSessionManager(db)
        _seed_sessions(mgr, 7)

        assert mgr.count_sessions() == 7
