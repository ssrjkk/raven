"""Postgres parity for the lifecycle sweep: one policy, two backends, four timestamp shapes.

The sweep's SQL is written once against `?` placeholders and translated for Postgres, and its cutoff
changes type per dialect — an epoch float for `monitor_checks`, an aware instant for `messages`.
Neither of those is testable on SQLite, so they run here against a real server: the one the CI Postgres job
starts, or any `DATABASE_URL` names. A run that selects them with no server answering is a failure, not a
field of skips.

Rows are namespaced by a per-run prefix and removed by their own owner; nothing in this file deletes
another test's data.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from raven.core.analytics import AnalyticsEngine
from raven.core.asyncdb import connect_backend
from raven.core.auth.store import AuthStore
from raven.core.coder.session import CodingSessionManager
from raven.core.db_postgres import PostgresDatabase
from raven.core.models import Message
from raven.core.monitor.models import Monitor, MonitorCheck, MonitorType
from raven.core.monitor.store import MonitorStore
from raven.core.retention import RetentionSweeper, _present_tables
from raven.core.routine.store import RoutineStore
from raven.core.task_engine.store import TaskStore

pytestmark = pytest.mark.integration

_DAY = 86_400.0


@pytest.fixture(scope="session")
async def pg_schema(pg_dsn: str) -> None:
    """Create the schema the way each owner does, because the sweep's table list is only ever as complete
    as the owners that ran. `PostgresDatabase` bootstraps the core tables alone, and every table owned by a
    store — `monitor_checks`, `analytics_snapshots`, `tasks` — appears only when that store connects, so a
    fixture that ran one bootstrap would let the probe test assert about tables no owner had created here."""
    core = PostgresDatabase(pg_dsn)
    await core.connect()
    await core.disconnect()

    stores: list[Any] = [
        MonitorStore(pg_dsn),
        RoutineStore(pg_dsn),
        TaskStore(pg_dsn),
        AuthStore(pg_dsn),
        CodingSessionManager(pg_dsn),
    ]
    for store in stores:
        await store._conn()
        await store.close()

    analytics = AnalyticsEngine(pg_dsn)
    await analytics.start()
    await analytics.stop()


def _run_prefix() -> str:
    return f"pgret-{uuid.uuid4().hex[:10]}"


def _epoch_ago(days: float) -> float:
    return datetime.now(UTC).timestamp() - days * _DAY


async def _fetch(dsn: str, sql: str, *args: Any) -> list[Any]:
    db = connect_backend(dsn)
    await db.connect()
    try:
        return await db.fetchall(sql, args)
    finally:
        await db.close()


async def test_the_sweep_ages_telemetry_on_postgres(pg_dsn: str, pg_schema: None) -> None:
    """`monitor_checks.checked_at` is epoch double precision there, so the cutoff has to bind as a float."""
    monitor_id = f"{_run_prefix()}-m1"
    store = MonitorStore(pg_dsn)
    sweeper = RetentionSweeper(pg_dsn, telemetry_days=30, telemetry_rows=2, history_days=0)
    try:
        await store.save_monitor(Monitor(id=monitor_id, name="retention parity", type=MonitorType.HTTP, user_id="u1"))
        for offset in range(7):
            await store.save_check(
                MonitorCheck(monitor_id=monitor_id, status="ok", checked_at=_epoch_ago(120 + offset))
            )
        for offset in range(3):
            await store.save_check(MonitorCheck(monitor_id=monitor_id, status="ok", checked_at=_epoch_ago(1 + offset)))

        removed = await sweeper.run_once()

        assert removed["monitor_checks"] == 8, f"the postgres sweep reported {removed}"
        kept = await _fetch(
            pg_dsn, "SELECT checked_at FROM monitor_checks WHERE monitor_id = ? ORDER BY checked_at DESC", monitor_id
        )
        assert len(kept) == 2, "the row cap left a different count on Postgres than on SQLite"
        assert all(row["checked_at"] >= _epoch_ago(3) for row in kept), "the cap kept the older rows"
    finally:
        await sweeper.stop()
        await store.delete_monitor(monitor_id)
        await store.close()


async def test_the_history_cutoff_binds_a_datetime_on_postgres(pg_dsn: str, pg_schema: None) -> None:
    """`messages.created_at` is a TIMESTAMPTZ there and ISO text on SQLite, so the cutoff has to bind as an
    instant: a float would compare a number against a time and a naive datetime would be read in the server's
    own zone instead of the UTC the writer meant."""
    session_id = f"{_run_prefix()}-s1"
    db = PostgresDatabase(pg_dsn)
    sweeper = RetentionSweeper(pg_dsn, telemetry_days=0, telemetry_rows=0, history_days=30)
    try:
        await db.connect()
        await db.get_or_create_session(session_id, "telegram", "u-1")
        await db.save_message(
            Message(
                session_id=session_id, role="user", content="old", created_at=datetime.now(UTC) - timedelta(days=400)
            )
        )
        await db.save_message(Message(session_id=session_id, role="user", content="new", created_at=datetime.now(UTC)))

        removed = await sweeper.run_once()

        assert removed.get("messages", 0) >= 1, f"the history pass deleted nothing on Postgres: {removed}"
        ages = [
            row["created_at"]
            for row in await _fetch(
                pg_dsn, "SELECT created_at FROM messages WHERE session_id = ? ORDER BY created_at", session_id
            )
        ]
        assert len(ages) == 1, "a message the cutoff should have taken survived, or the recent one went away"
    finally:
        await sweeper.stop()
        await db.delete_session(session_id)
        await db.disconnect()


async def test_the_present_table_probe_reads_the_postgres_catalog(pg_dsn: str, pg_schema: None) -> None:
    """The sweep skips the tables an installation never created, so on Postgres that list comes from the
    catalog rather than a guess. `pg_schema` is what makes the assertion mean anything: the tables it names
    were created here, by the owners that create them in production."""
    db = connect_backend(pg_dsn)
    await db.connect()
    try:
        present = await _present_tables(db)
        assert {"monitor_checks", "messages", "analytics_snapshots"} <= present, "the catalog probe found nothing"
        assert all(name == name.lower() for name in present)
    finally:
        await db.close()
