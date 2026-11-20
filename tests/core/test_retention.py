"""The data-lifecycle contract: what may be deleted, by whom, and what must never be.

Two of these checks are the point of the wave rather than coverage of it: every table the schema
creates has to declare a policy, and the sweep has to keep its hands off the tables another owner
already bounds. The first is what keeps the second true as the schema grows.

Every table here is created by the store that owns it, and every row is written by the production
writer, because the shape of a stored timestamp differs per column and per backend — a fixture that
invented its own DDL would test the sweep against a schema the product does not have.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from raven.core.analytics import AnalyticsEngine
from raven.core.asyncdb import AsyncDB, connect_backend
from raven.core.config import Settings
from raven.core.db import Database
from raven.core.models import Message
from raven.core.monitor.models import Monitor, MonitorCheck
from raven.core.monitor.store import MonitorStore
from raven.core.outbox import Outbox
from raven.core.retention import POLICIES, RetentionSweeper, cutoff, unit_for
from raven.core.routine.models import Routine, RoutineLog
from raven.core.routine.store import RoutineStore
from raven.core.services.persister import SQLitePersister

ROOT = Path(__file__).resolve().parents[2]
_CREATE_TABLE = re.compile(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+[\"'`]?([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_DAY = 86_400.0
_METRIC = "http_requests_total"
SweeperFactory = Callable[..., RetentionSweeper]
"""The `sweepers` fixture: build a sweeper, and the fixture stops it when the test ends."""


def _epoch_ago(days: float) -> float:
    return datetime.now(UTC).timestamp() - days * _DAY


def _schema_tables() -> set[str]:
    """Every table name the production packages ask a database to create."""
    tables: set[str] = set()
    for package in ("raven", "aios", "ravencode"):
        for source in (ROOT / package).rglob("*.py"):
            tables.update(match.lower() for match in _CREATE_TABLE.findall(source.read_text(encoding="utf-8")))
    return tables


async def _scalar(path: Path, sql: str, params: tuple[Any, ...] = ()) -> int:
    db = connect_backend(path)
    await db.connect()
    try:
        row = await db.fetchone(sql, params)
        assert row is not None, sql
        return int(row["n"])
    finally:
        await db.close()


async def _values(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
    db = connect_backend(path)
    await db.connect()
    try:
        return [row[0] for row in await db.fetchall(sql, params)]
    finally:
        await db.close()


async def _has_table(path: Path, name: str) -> bool:
    db = connect_backend(path)
    await db.connect()
    try:
        row = await db.fetchone("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))
        return row is not None
    finally:
        await db.close()


def _count_sql(table: str, where: str = "") -> str:
    return f"SELECT COUNT(*) AS n FROM {table}" + (f" WHERE {where}" if where else "")


async def _seed_checks(path: Path, monitor_id: str, old: int, recent: int) -> None:
    store = MonitorStore(path)
    try:
        await store.save_monitor(Monitor(id=monitor_id, name="retention probe"))
        for offset in range(old):
            await store.save_check(
                MonitorCheck(monitor_id=monitor_id, status="ok", checked_at=_epoch_ago(120 + offset))
            )
        for offset in range(recent):
            await store.save_check(MonitorCheck(monitor_id=monitor_id, status="ok", checked_at=_epoch_ago(1 + offset)))
    finally:
        await store.close()


async def _seed_logs(path: Path, routine_id: str, old: int, recent: int) -> None:
    store = RoutineStore(path)
    try:
        await store.save_routine(Routine(id=routine_id, name="retention probe"))
        for offset in range(old):
            await store.save_log(RoutineLog(routine_id=routine_id, status="ok", created_at=_epoch_ago(90 + offset)))
        for offset in range(recent):
            await store.save_log(RoutineLog(routine_id=routine_id, status="ok", created_at=_epoch_ago(2 + offset)))
    finally:
        await store.close()


async def _seed_snapshots(path: Path, old: int, recent: int) -> None:
    rows = [(int(_epoch_ago(200 + offset)), _METRIC, 1.0) for offset in range(old)]
    rows += [(int(_epoch_ago(3 + offset)), _METRIC, 2.0) for offset in range(recent)]
    db = connect_backend(path)
    await db.connect()
    try:
        await db.executemany("INSERT INTO analytics_snapshots (ts, metric_name, metric_value) VALUES (?, ?, ?)", rows)
        await db.commit()
    finally:
        await db.close()


async def _seed_conversation(path: Path, session_id: str, ages_days: list[float]) -> None:
    db = Database(path)
    await db.connect()
    try:
        await db.get_or_create_session(session_id, channel="telegram", user_id="u-1")
        for offset, days in enumerate(ages_days):
            await db.save_message(
                Message(
                    session_id=session_id,
                    role="user",
                    content=f"{session_id}-{offset}",
                    created_at=datetime.now(UTC) - timedelta(days=days),
                )
            )
    finally:
        await db.disconnect()


async def _seed_dropped_outbox_row(path: Path) -> None:
    db = connect_backend(path)
    await db.connect()
    try:
        await db.execute(
            "INSERT INTO outbox (channel_id, session_id, text, attempts, next_due, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("c-1", "s-1", "never arrived", 5, _epoch_ago(999), "dropped", _epoch_ago(999)),
        )
        await db.commit()
    finally:
        await db.close()


async def _never_sends(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("the outbox worker must not send during a retention test")


@pytest.fixture
async def live_db(tmp_path: Path) -> AsyncIterator[Path]:
    """One database whose tables were each created by the store that owns it."""
    path = tmp_path / "raven.db"

    core = Database(path)
    await core.connect()
    await core.disconnect()

    for store in (MonitorStore(path), RoutineStore(path)):
        await store._conn()
        await store.close()

    engine = AnalyticsEngine(path, snapshot_interval=3600)
    await engine.start()
    await engine.stop()

    outbox = Outbox(path, _never_sends)
    await outbox.start()
    await outbox.stop()

    persister = SQLitePersister(path)
    await persister._ensure()
    await persister.close()

    yield path


@pytest.fixture
async def sweepers() -> AsyncIterator[Callable[..., RetentionSweeper]]:
    """Build sweepers for a test and release their handles afterwards.

    A sweeper keeps its connection open between passes, and an aiosqlite worker that never receives
    `close()` stays alive and holds the interpreter: a leaked sweeper hangs the whole test process,
    which is worse than a failed test.
    """
    created: list[RetentionSweeper] = []

    def make(db_path: str | Path, **kwargs: Any) -> RetentionSweeper:
        sweeper = RetentionSweeper(db_path, **kwargs)
        created.append(sweeper)
        return sweeper

    yield make
    for sweeper in created:
        await sweeper.stop()


# --- the gates that keep the schema honest -------------------------------------------------------


def test_every_table_the_schema_creates_declares_a_lifecycle_policy() -> None:
    tables = _schema_tables()
    assert tables, "the CREATE TABLE scan found no tables: the probe is broken, not the schema empty"
    undocumented = sorted(tables - set(POLICIES))
    assert not undocumented, f"tables that grow with no retention policy: {undocumented}"


def test_no_policy_names_a_table_the_schema_stopped_creating() -> None:
    orphaned = sorted(set(POLICIES) - _schema_tables())
    assert not orphaned, f"retention policies for tables that no longer exist: {orphaned}"


def test_a_table_another_owner_bounds_is_never_aged_by_the_sweep() -> None:
    wide_open = RetentionSweeper("data/never-opened.db", telemetry_days=36_500, telemetry_rows=1, history_days=36_500)
    for policy in POLICIES.values():
        if policy.kind in {"owner_purged", "bounded", "unused"}:
            assert wide_open._days_for(policy) == 0.0, policy.table
            assert not wide_open._is_capped(policy), policy.table
        elif policy.kind == "history":
            assert wide_open._days_for(policy) == 36_500, policy.table
            assert not wide_open._is_capped(policy), policy.table
        else:
            assert wide_open._days_for(policy) > 0, policy.table
            assert wide_open._is_capped(policy), policy.table


def test_history_is_kept_forever_until_it_is_asked_away(tmp_path: Path) -> None:
    """Zero is the shipped default, and it means the sweep never deletes what a person wrote."""
    sweeper = RetentionSweeper(tmp_path / "raven.db")
    assert sweeper.history_days == 0.0
    for policy in POLICIES.values():
        if policy.kind == "history":
            assert sweeper._days_for(policy) == 0.0, policy.table


# --- measured behaviour --------------------------------------------------------------------------


async def test_the_sweep_ages_telemetry_and_caps_what_age_alone_leaves(live_db: Path, sweepers: SweeperFactory) -> None:
    await _seed_checks(live_db, "m-1", old=7, recent=3)
    await _seed_checks(live_db, "m-2", old=0, recent=2)
    await _seed_logs(live_db, "r-1", old=6, recent=4)
    await _seed_snapshots(live_db, old=3, recent=2)

    removed = await sweepers(live_db, telemetry_days=30, telemetry_rows=2, history_days=0).run_once()

    # Age takes 7 + 6 + 3; the cap then trims m-1's 3 survivors and r-1's 4 down to two each.
    assert removed == {"monitor_checks": 8, "routine_logs": 8, "analytics_snapshots": 3}
    assert await _scalar(live_db, _count_sql("monitor_checks")) == 4
    assert await _scalar(live_db, _count_sql("monitor_checks", "monitor_id = ?"), ("m-1",)) == 2
    assert await _scalar(live_db, _count_sql("routine_logs")) == 2
    assert await _scalar(live_db, _count_sql("analytics_snapshots", "metric_name = ?"), (_METRIC,)) == 2


async def test_the_rows_a_cap_keeps_are_the_newest_ones(live_db: Path, sweepers: SweeperFactory) -> None:
    await _seed_checks(live_db, "m-1", old=0, recent=5)
    await sweepers(live_db, telemetry_days=0, telemetry_rows=2, history_days=0).run_once()

    kept = await _values(live_db, "SELECT checked_at FROM monitor_checks ORDER BY checked_at DESC")
    assert len(kept) == 2, "the cap left a different number of rows than it was told to keep"
    assert all(value >= _epoch_ago(3) for value in kept), "the cap dropped recent rows and kept older ones"


async def test_turning_the_age_knob_off_leaves_the_row_cap_running(live_db: Path, sweepers: SweeperFactory) -> None:
    """`RETENTION_TELEMETRY_DAYS=0` is documented as "no age rule", not as "no bound at all"."""
    await _seed_checks(live_db, "m-1", old=7, recent=3)

    removed = await sweepers(live_db, telemetry_days=0, telemetry_rows=2, history_days=0).run_once()

    assert removed == {"monitor_checks": 8}, "the age switch silenced the row cap with it"
    kept = await _values(live_db, "SELECT checked_at FROM monitor_checks ORDER BY checked_at DESC")
    assert len(kept) == 2 and all(value >= _epoch_ago(3) for value in kept)


async def test_conversations_survive_every_telemetry_setting_and_die_only_by_their_own_knob(
    live_db: Path, sweepers: SweeperFactory
) -> None:
    await _seed_conversation(live_db, "s-old", [400.0, 2.0])
    await _seed_conversation(live_db, "s-new", [1.0])

    telemetry_only = sweepers(live_db, telemetry_days=1, telemetry_rows=10, history_days=0)
    assert await telemetry_only.run_once() == {}
    assert await _scalar(live_db, _count_sql("messages")) == 3
    assert await _scalar(live_db, _count_sql("sessions")) == 2

    opted_in = sweepers(live_db, telemetry_days=1, telemetry_rows=10, history_days=30)
    assert await opted_in.run_once() == {"messages": 1}
    assert await _scalar(live_db, _count_sql("messages")) == 2
    assert await _scalar(live_db, _count_sql("sessions")) == 2


async def test_the_sweep_leaves_tables_their_own_owner_bounds(live_db: Path, sweepers: SweeperFactory) -> None:
    """`outbox` has an age column and a purger of its own; the sweep must still walk past it."""
    await _seed_dropped_outbox_row(live_db)
    await sweepers(live_db, telemetry_days=1, telemetry_rows=10, history_days=1).run_once()
    assert await _scalar(live_db, _count_sql("outbox")) == 1


async def test_a_policy_table_this_install_never_created_does_not_stop_the_sweep(
    tmp_path: Path, sweepers: SweeperFactory
) -> None:
    """`entities` appears on the persister's first write, so an install can legitimately lack it forever.

    The sweep used to die on it: one absent table aborted the whole pass, so the telemetry that *was*
    there aged on a database that had the rows and never on the one that raised.
    """
    path = tmp_path / "partial.db"
    core = Database(path)
    await core.connect()
    await core.disconnect()
    assert not await _has_table(path, "entities"), "the fixture became a full schema and proves nothing"

    await _seed_checks(path, "m-1", old=7, recent=1)
    await _seed_conversation(path, "s-old", [400.0])

    removed = await sweepers(path, telemetry_days=30, telemetry_rows=2, history_days=30).run_once()

    assert removed == {"monitor_checks": 7, "messages": 1}
    assert await _scalar(path, _count_sql("monitor_checks")) == 1


async def test_a_second_sweep_finds_nothing(live_db: Path, sweepers: SweeperFactory) -> None:
    await _seed_checks(live_db, "m-1", old=4, recent=1)
    await _seed_logs(live_db, "r-1", old=4, recent=1)
    sweeper = sweepers(live_db, telemetry_days=30, telemetry_rows=1, history_days=0)
    assert await sweeper.run_once()
    assert await sweeper.run_once() == {}


async def test_parallel_sweeps_share_one_handle_and_delete_the_rows_once(
    live_db: Path, sweepers: SweeperFactory
) -> None:
    """The storage lesson from this repo: a single caller proves nothing about concurrent ones."""
    await _seed_checks(live_db, "m-1", old=20, recent=5)
    await _seed_checks(live_db, "m-2", old=20, recent=5)

    sweeper = sweepers(live_db, telemetry_days=30, telemetry_rows=3, history_days=0)
    results = await asyncio.gather(*(sweeper.run_once() for _ in range(6)))
    assert all(isinstance(result, dict) for result in results)
    # Per monitor the age pass drops 20 and the cap drops 2 more: 44 rows, each of them counted once.
    assert sum(sum(result.values()) for result in results) == 44, "a row was removed or reported twice"
    assert await _scalar(live_db, _count_sql("monitor_checks", "monitor_id = ?"), ("m-1",)) == 3
    assert await _scalar(live_db, _count_sql("monitor_checks", "monitor_id = ?"), ("m-2",)) == 3


# --- the service wrapper -------------------------------------------------------------------------


async def test_a_disabled_sweep_never_opens_the_database(tmp_path: Path) -> None:
    sweeper = RetentionSweeper(tmp_path / "raven.db", enabled=False)
    await sweeper.start()
    assert sweeper._db is None
    assert sweeper._worker is None
    assert not (tmp_path / "raven.db").exists()
    await sweeper.stop()


async def test_the_loop_sweeps_on_its_interval_and_stops_cleanly(live_db: Path) -> None:
    passes: list[dict[str, int]] = []

    class Counting(RetentionSweeper):
        async def run_once(self) -> dict[str, int]:
            result = await super().run_once()
            passes.append(result)
            return result

    await _seed_checks(live_db, "m-1", old=9, recent=1)

    sweeper = Counting(live_db, telemetry_days=30, telemetry_rows=5, history_days=0, interval=0.02)
    await sweeper.start()
    await sweeper.start()
    try:
        await asyncio.sleep(0.15)
    finally:
        await sweeper.stop()

    assert sweeper._worker is None and sweeper._db is None
    assert len(passes) >= 2, "a second sweep never ran"
    assert passes[0], "the first sweep deleted nothing"
    assert not any(passes[1:]), "the table was swept again as if it still had stale rows"


async def test_a_failing_sweep_is_logged_and_the_loop_survives(tmp_path: Path) -> None:
    attempts: list[int] = []

    class Broken(RetentionSweeper):
        async def _sweep(self, db: AsyncDB) -> dict[str, int]:
            attempts.append(1)
            msg = "simulated lock failure"
            raise RuntimeError(msg)

    sweeper = Broken(tmp_path / "raven.db", interval=0.02)
    await sweeper.start()
    await asyncio.sleep(0.09)
    await sweeper.stop()
    assert len(attempts) >= 2, "one failure stopped the sweep for the rest of the process life"


# --- the per-dialect shape of a cutoff -----------------------------------------------------------


def test_a_cutoff_is_shaped_the_way_the_column_stores_time() -> None:
    assert isinstance(cutoff(POLICIES["monitor_checks"], 30, "sqlite"), float)

    iso = cutoff(POLICIES["messages"], 30, "sqlite")
    assert isinstance(iso, str) and "T" in iso, "SQLite stores messages.created_at as ISO text"

    text = cutoff(POLICIES["entities"], 30, "sqlite")
    assert isinstance(text, str) and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", text)

    stamp = cutoff(POLICIES["messages"], 30, "postgresql")
    assert isinstance(stamp, datetime) and stamp.tzinfo is UTC, "a TIMESTAMPTZ column holds an instant"


def test_the_columns_stamped_differently_per_dialect_say_so() -> None:
    """These pairs are why a cutoff needs a dialect: the same column holds a different type."""
    assert unit_for(POLICIES["messages"], "sqlite") == "iso"
    assert unit_for(POLICIES["messages"], "postgresql") == "timestamptz"
    assert unit_for(POLICIES["entities"], "sqlite") == "sql_datetime"
    assert unit_for(POLICIES["entities"], "postgresql") == "epoch_s"
    for table in ("monitor_checks", "routine_logs", "analytics_snapshots", "coding_sessions"):
        assert unit_for(POLICIES[table], "sqlite") == "epoch_s", table
        assert unit_for(POLICIES[table], "postgresql") == "epoch_s", table


# --- configuration refuses to be wrong -----------------------------------------------------------


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("RETENTION_INTERVAL_SECONDS", "5"),
        ("RETENTION_TELEMETRY_DAYS", "-1"),
        ("RETENTION_HISTORY_DAYS", "-1"),
        ("RETENTION_TELEMETRY_ROWS", "10"),
    ],
)
def test_an_unusable_retention_setting_is_refused_at_load(
    monkeypatch: pytest.MonkeyPatch, env_name: str, value: str
) -> None:
    """Measured on the path an operator actually takes — an env var — not on a Python kwarg."""
    monkeypatch.setenv(env_name, value)
    with pytest.raises(ValueError, match=env_name):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_the_shipped_defaults_sweep_telemetry_and_keep_history() -> None:
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert defaults.retention_enabled is True
    assert defaults.retention_telemetry_days > 0
    assert defaults.retention_telemetry_rows >= 50
    assert defaults.retention_history_days == 0.0
    assert defaults.retention_interval_seconds >= 60
