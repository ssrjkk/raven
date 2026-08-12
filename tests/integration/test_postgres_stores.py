from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from raven.core.analytics import AnalyticsEngine
from raven.core.asyncdb import postgres_dsn
from raven.core.metrics import metrics
from raven.core.monitor.models import Monitor, MonitorCheck, MonitorStatus, MonitorType
from raven.core.outbox import Outbox
from raven.core.routine.models import Routine, RoutineAction, RoutineLog, RoutineStatus, RoutineTrigger
from raven.core.task_engine.models import Task, TaskPriority, TaskStatus, TaskStep

pytestmark = pytest.mark.integration

_DEFAULT_DSN = "postgresql://raven:raven@localhost:5432/raven"


async def _clean_table(dsn: str, table: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"DELETE FROM {table}")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def pg_dsn() -> str:
    dsn = postgres_dsn() or _DEFAULT_DSN
    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg not installed (install raven-agent[postgres])")
    try:
        conn = await asyncpg.connect(dsn, timeout=3)
        await conn.close()
    except Exception as e:
        pytest.skip(f"Postgres not available at {dsn}: {e}")
    return dsn


@pytest.fixture(scope="session")
async def pg_schema(pg_dsn: str) -> None:
    from raven.core.db_postgres import PostgresDatabase

    db = PostgresDatabase(pg_dsn)
    await db.connect()
    await db.disconnect()


async def test_task_store_crud(pg_dsn: str, pg_schema: None) -> None:
    from raven.core.task_engine.store import TaskStore

    store = TaskStore(pg_dsn)
    task = Task(
        id=f"t-{uuid.uuid4().hex[:12]}",
        user_id="u1",
        channel="test",
        goal="build a bridge",
        priority=TaskPriority.HIGH,
    )
    task.steps = [
        TaskStep(task_id=task.id, order=1, description="design", tool="file_write"),
        TaskStep(task_id=task.id, order=2, description="build", tool="shell"),
    ]
    await store.save_task(task)

    loaded = await store.load_task(task.id)
    assert loaded is not None
    assert loaded.goal == "build a bridge"
    assert loaded.priority == TaskPriority.HIGH
    assert len(loaded.steps) == 2
    assert loaded.steps[0].description == "design"

    rows = await store.list_tasks(user_id="u1")
    assert any(r.id == task.id for r in rows)
    assert await store.count_tasks(user_id="u1") >= 1

    await store.update_status(task.id, TaskStatus.COMPLETED)
    reloaded = await store.load_task(task.id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.COMPLETED

    await store.delete_task(task.id)
    assert await store.load_task(task.id) is None
    await store.close()


async def test_task_store_upsert(pg_dsn: str, pg_schema: None) -> None:
    from raven.core.task_engine.store import TaskStore

    store = TaskStore(pg_dsn)
    task = Task(id=f"t-{uuid.uuid4().hex[:12]}", user_id="u1", goal="v1")
    await store.save_task(task)
    task.goal = "v2"
    await store.save_task(task)
    loaded = await store.load_task(task.id)
    assert loaded is not None
    assert loaded.goal == "v2"
    await store.delete_task(task.id)
    await store.close()


async def test_monitor_store_crud(pg_dsn: str, pg_schema: None) -> None:
    from raven.core.monitor.store import MonitorStore

    store = MonitorStore(pg_dsn)
    monitor = Monitor(
        id=f"m-{uuid.uuid4().hex[:12]}",
        name="uptime",
        type=MonitorType.HTTP,
        target="https://example.com",
        user_id="u1",
        slo_target=0.95,
        group="web",
    )
    await store.save_monitor(monitor)

    loaded = await store.load_monitor(monitor.id)
    assert loaded is not None
    assert loaded.type == MonitorType.HTTP
    assert loaded.target == "https://example.com"
    assert loaded.slo_target == 0.95
    assert loaded.group == "web"

    assert any(m.id == monitor.id for m in await store.list_monitors(user_id="u1"))
    assert await store.count_monitors(user_id="u1") >= 1

    check = MonitorCheck(
        id=f"c-{uuid.uuid4().hex[:12]}",
        monitor_id=monitor.id,
        status="up",
        result={"status": "up"},
        triggered=False,
        checked_at=time.time(),
        response_time_ms=120.5,
    )
    await store.save_check(check)
    checks = await store.get_checks(monitor.id)
    assert len(checks) == 1
    assert checks[0].status == "up"
    assert checks[0].response_time_ms == 120.5

    slo = await store.get_slo_stats(monitor.id, 86400)
    assert slo["total"] == 1
    assert slo["ok"] == 1

    await store.delete_monitor(monitor.id)
    assert await store.load_monitor(monitor.id) is None
    await store.close()


async def test_routine_store_crud(pg_dsn: str, pg_schema: None) -> None:
    from raven.core.routine.store import RoutineStore

    store = RoutineStore(pg_dsn)
    routine = Routine(
        id=f"r-{uuid.uuid4().hex[:12]}",
        name="morning briefing",
        action=RoutineAction.SEND_BRIEFING,
        trigger=RoutineTrigger.SCHEDULED,
        schedule="08:00",
        user_id="u1",
        channel="test",
    )
    await store.save_routine(routine)

    loaded = await store.load_routine(routine.id)
    assert loaded is not None
    assert loaded.action == RoutineAction.SEND_BRIEFING
    assert loaded.schedule == "08:00"

    assert any(r.id == routine.id for r in await store.list_routines(user_id="u1"))
    assert await store.count_routines(user_id="u1") >= 1

    await store.update_status(routine.id, RoutineStatus.PAUSED)
    assert (await store.load_routine(routine.id)) is not None

    await store.save_log(
        RoutineLog(
            id=f"l-{uuid.uuid4().hex[:12]}",
            routine_id=routine.id,
            status="ok",
            message="sent",
            created_at=time.time(),
        )
    )
    logs = await store.get_logs(routine.id)
    assert len(logs) == 1
    assert logs[0].status == "ok"

    await store.delete_routine(routine.id)
    assert await store.load_routine(routine.id) is None
    await store.close()


async def test_auth_store_crud(pg_dsn: str, pg_schema: None) -> None:
    from raven.core.auth.store import AuthStore

    store = AuthStore(pg_dsn)
    username = f"user-{uuid.uuid4().hex[:8]}"
    user = await store.create_user(username, password="secret123", display_name="Test User", role="admin")
    assert user.username == username

    found = await store.get_user(username)
    assert found is not None
    assert found.display_name == "Test User"
    assert found.role.value == "admin"

    assert await store.authenticate(username, "secret123") is not None
    assert await store.authenticate(username, "wrong-password") is None

    await store.update_role(username, "user")
    updated = await store.get_user(username)
    assert updated is not None
    assert updated.role.value == "user"

    assert any(u.username == username for u in await store.list_users())
    await store.close()


async def test_outbox_delivery(pg_dsn: str, pg_schema: None) -> None:
    await _clean_table(pg_dsn, "outbox")
    sent: list[tuple[str, str, str]] = []

    async def send(channel_id: str, session_id: str, text: str) -> None:
        sent.append((channel_id, session_id, text))

    outbox = Outbox(pg_dsn, send, retry_interval=3600)
    await outbox.start()
    try:
        await outbox.enqueue("ch1", "sess1", "hello")
        assert await outbox.pending_count() == 1
        delivered = await outbox.flush()
        assert delivered == 1
        assert await outbox.pending_count() == 0
        assert sent == [("ch1", "sess1", "hello")]
    finally:
        await outbox.stop()


async def test_outbox_drop_after_max_attempts(pg_dsn: str, pg_schema: None) -> None:
    await _clean_table(pg_dsn, "outbox")
    async def fail(channel_id: str, session_id: str, text: str) -> None:
        raise RuntimeError("boom")

    outbox = Outbox(pg_dsn, fail, max_attempts=2, retry_interval=3600, backoff_base=1)
    await outbox.start()
    try:
        await outbox.enqueue("ch2", "sess2", "will fail")
        await outbox.flush()
        await outbox.flush()
        assert await outbox.dropped_count() == 1
        assert await outbox.pending_count() == 0
    finally:
        await outbox.stop()


async def test_analytics_engine_snapshot_and_query(pg_dsn: str, pg_schema: None) -> None:
    eng = AnalyticsEngine(pg_dsn, snapshot_interval=3600)
    await eng.start()
    try:
        metrics.inc("test_analytics_counter", {"channel": "x"})
        await eng._snapshot()
        names = await eng.query_metrics_list()
        assert any("test_analytics_counter" in n for n in names)
        summary = await eng.query_summary(since=0)
        assert summary["total_data_points"] >= 1
        series = await eng.query_series(
            next(n for n in names if "test_analytics_counter" in n),
            since=0,
            bucket="1m",
        )
        assert len(series) >= 1
    finally:
        await eng.stop()


async def test_persister_crud(pg_dsn: str, pg_schema: None) -> None:
    from raven.core.services.persister import SQLitePersister

    persister = SQLitePersister(pg_dsn)
    try:
        obj_id = await persister.insert("widgets", {"name": "gear", "qty": 3})
        got = await persister.get("widgets", obj_id)
        assert got is not None
        assert got["name"] == "gear"
        results = await persister.search("widgets", "gear")
        assert len(results) >= 1
        assert await persister.delete("widgets", obj_id) is True
    finally:
        await persister.close()
