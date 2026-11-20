"""Postgres parity for the lifecycle sweep: one policy, two backends, four timestamp shapes.

The sweep's SQL is written once against `?` placeholders and translated for Postgres, and its cutoff
changes type per dialect — an epoch float for `monitor_checks`, an aware `datetime` for `messages`.
Neither of those is testable on SQLite, so they run here against the CI Postgres service and skip when
no server answers.

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
from raven.core.asyncdb import connect_backend, postgres_dsn
from raven.core.db_postgres import PostgresDatabase
from raven.core.models import Message
from raven.core.monitor.models import Monitor, MonitorCheck, MonitorType
from raven.core.monitor.store import MonitorStore
from raven.core.retention import RetentionSweeper, _present_tables

pytestmark = pytest.mark.integration

_DEFAULT_DSN = "postgresql://raven:raven@localhost:5432/raven"
_DAY = 86_400.0


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
    db = PostgresDatabase(pg_dsn)
    await db.connect()
    await db.disconnect()


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
    """`messages.created_at` is a TIMESTAMPTZ there and ISO text on SQLite, so the bind is neither a
    string nor a naive datetime: the naive one is accepted and then re-read in the server's zone."""
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
    """The sweep skips what is not there, so on Postgres that list comes from pg_catalog.

    `analytics_snapshots` is the case that matters: the core schema does not create it, the analytics
    engine does on its first start, so the probe has to report the install as it is and pick the table
    up when it appears rather than from a list written next to the DDL.
    """
    db = connect_backend(pg_dsn)
    engine = AnalyticsEngine(pg_dsn, snapshot_interval=3600)
    await db.connect()
    try:
        present = await _present_tables(db)
        assert {"monitor_checks", "messages", "sessions"} <= present, "the catalog probe found nothing"
        assert all(name == name.lower() for name in present)

        await engine.start()
        try:
            assert "analytics_snapshots" in await _present_tables(db), "the probe stayed at what it started with"
        finally:
            await engine.stop()
    finally:
        await db.close()
