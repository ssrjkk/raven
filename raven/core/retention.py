"""Every table this install grows has to say how it stops growing.

Row counts are not only a disk question. A monitor polled every minute writes 1 440 rows a day into
`monitor_checks`, the routines log every run, and `analytics_snapshots` stores a row per metric per
flush — so a gateway left running for a year answers its own history screens out of millions of rows
it never shows again. Twenty-two tables exist in the schema; each one carries exactly one entry in
POLICIES below, and `tests/core/test_retention.py` fails the build when a `CREATE TABLE` appears in
the tree with no policy, because the alternative is remembering which tables were audited when.

Two rules the shape follows:

- Telemetry ages out by default. Nobody needs a year of per-minute check rows to read a dashboard.
- Anything a person wrote (chat history, coding sessions, stored entities) is never deleted unless
  `retention_history_days` is raised above zero. Disk is cheap and a conversation is not, so the
  conservative direction is "keep", and the destructive switch is the one that has to be pulled.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from raven.core.asyncdb import AsyncDB, connect_backend, is_postgres_dsn
from raven.core.config import settings

PolicyKind = Literal["telemetry", "history", "owner_purged", "bounded", "unused"]
AgeUnit = Literal["epoch_s", "iso", "sql_datetime", "timestamp"]
Dialect = Literal["sqlite", "postgresql"]

_DELETE_CHUNK = 500
"""Ids per DELETE statement: an over-cap sweep can name ten thousand rows in one table."""


@dataclass(frozen=True)
class TablePolicy:
    table: str
    kind: PolicyKind
    age_column: str | None = None
    unit: AgeUnit | dict[Dialect, AgeUnit] = "epoch_s"
    parent_column: str | None = None
    id_column: str = "id"
    why: str = ""


POLICIES: dict[str, TablePolicy] = {
    policy.table: policy
    for policy in (
        TablePolicy(
            "monitor_checks",
            "telemetry",
            "checked_at",
            "epoch_s",
            parent_column="monitor_id",
            why="one row per poll of one monitor; grows faster than every other table combined",
        ),
        TablePolicy(
            "routine_logs",
            "telemetry",
            "created_at",
            "epoch_s",
            parent_column="routine_id",
            why="one row per scheduled run, kept after the routine was edited away from its task",
        ),
        TablePolicy(
            "analytics_snapshots",
            "telemetry",
            "ts",
            "epoch_s",
            parent_column="metric_name",
            why="one row per metric per flush; the series behind the charts is the point, its first year is not",
        ),
        TablePolicy(
            "rss_seen_items",
            "unused",
            why="created on both backends and never read or written: RSS dedupe lives in a process-local "
            "dict with a 7-day TTL (raven/core/monitor/checkers/rss.py), so it resets on every restart",
        ),
        TablePolicy(
            "messages",
            "history",
            "created_at",
            {"sqlite": "iso", "postgresql": "timestamp"},
            why="the conversation itself; only `retention_history_days` makes this deletable",
        ),
        TablePolicy(
            "sessions",
            "history",
            "created_at",
            {"sqlite": "iso", "postgresql": "timestamp"},
            why="a session row is the index into a conversation, so it dies with the messages, not before "
            "them; `Database.get_or_create_session` writes the column as ISO text, not as the DDL default",
        ),
        TablePolicy(
            "coding_sessions",
            "history",
            "updated_at",
            "epoch_s",
            why="ravencode transcripts; a finished run is what a person comes back to read",
        ),
        TablePolicy(
            "entities",
            "history",
            "created_at",
            {"sqlite": "sql_datetime", "postgresql": "epoch_s"},
            why="the service store's rows, created by tools on a person's behalf; the column is DB-stamped "
            "and numeric on Postgres but text on SQLite, so its unit differs per dialect",
        ),
        TablePolicy(
            "tasks",
            "owner_purged",
            "created_at",
            why="TaskEngineStore.purge_finished() drops terminal tasks on a loop; work that is pending, "
            "running or paused must survive every sweep",
        ),
        TablePolicy(
            "task_steps",
            "owner_purged",
            why="deleted with their task by TaskEngineStore.purge_finished()",
        ),
        TablePolicy(
            "auth_sessions",
            "owner_purged",
            "expires_at",
            why="AuthStore.purge_expired() removes rows the moment they stop authenticating anyone",
        ),
        TablePolicy(
            "auth_email_tokens",
            "owner_purged",
            "expires_at",
            why="purged with the sessions, and consumed on use",
        ),
        TablePolicy(
            "outbox",
            "owner_purged",
            "created_at",
            why="OutboxWorker deletes a row when it sends and ages out the dropped ones",
        ),
        TablePolicy("users", "bounded", why="one row per person who ever messaged the bot"),
        TablePolicy("auth_users", "bounded", why="one row per registered account"),
        TablePolicy("monitors", "bounded", why="one row per monitor someone created"),
        TablePolicy("routines", "bounded", why="one row per routine someone created"),
        TablePolicy("secrets", "bounded", why="one row per key, replaced on write"),
        TablePolicy("plugin_state", "bounded", why="one row per plugin and key, replaced on write"),
        TablePolicy("_migrations", "bounded", why="one row per applied migration; the ledger is the schema"),
        TablePolicy("bench", "bounded", why="scratch rows written by `raven benchmark`, a CLI run by hand"),
        TablePolicy(
            "checkpoints",
            "unused",
            why="created by migration 3 and never written: the fine-tune checkpoints live on disk, not here",
        ),
    )
}


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def check_identifiers(policy: TablePolicy) -> None:
    """Refuse to splice anything that is not a bare SQL identifier.

    Neither backend takes a table or column name as a parameter, so the sweep interpolates them and the
    safety of those statements rests entirely on `POLICIES` spelling names the way a schema does. That
    is checked on the way to building a statement instead of trusted from the comment above the
    f-string: the registry grows whenever a store adds a table, and a quoted, qualified or dotted name
    reaching a slot would travel straight into executed SQL.
    """
    for name in (policy.table, policy.age_column, policy.parent_column, policy.id_column):
        if name is not None and not _IDENTIFIER.fullmatch(name):
            msg = f"retention policy {policy.table!r} spells a non-identifier: {name!r}"
            raise ValueError(msg)


def unit_for(policy: TablePolicy, dialect: Dialect) -> AgeUnit:
    return policy.unit[dialect] if isinstance(policy.unit, dict) else policy.unit


def cutoff(policy: TablePolicy, days: float, dialect: Dialect) -> float | str | datetime:
    """The value to compare `policy.age_column` against, shaped the way that column actually stores time."""
    moment = datetime.now(UTC) - timedelta(days=days)
    match unit_for(policy, dialect):
        case "epoch_s":
            return moment.timestamp()
        case "iso":
            return moment.isoformat()
        case "sql_datetime":
            return moment.strftime("%Y-%m-%d %H:%M:%S")
        case "timestamp":
            # asyncpg binds a TIMESTAMP parameter as a naive datetime and rejects the string form.
            return moment.replace(tzinfo=None)
    raise AssertionError(f"unreachable unit for {policy.table}")


_TABLE_NAMES: dict[Dialect, str] = {
    "sqlite": "SELECT name AS table_name FROM sqlite_master WHERE type = 'table'",
    "postgresql": "SELECT tablename AS table_name FROM pg_catalog.pg_tables WHERE schemaname = 'public'",
}


async def _present_tables(db: AsyncDB) -> set[str]:
    """The tables this database actually has. A store creates its table on first use, so an install is
    legitimately missing some of the schema forever, and the sweep has to age the rows it can reach."""
    dialect: Dialect = "postgresql" if db.dialect == "postgresql" else "sqlite"
    rows = await db.fetchall(_TABLE_NAMES[dialect])
    return {str(row["table_name"]).lower() for row in rows}


class RetentionSweeper:
    """Deletes what the policy says is stale, on a loop, from inside the gateway."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        telemetry_days: float | None = None,
        telemetry_rows: int | None = None,
        history_days: float | None = None,
        interval: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._db_path = str(db_path if db_path is not None else settings.resolved_db_path)
        self.telemetry_days = settings.retention_telemetry_days if telemetry_days is None else telemetry_days
        self.telemetry_rows = settings.retention_telemetry_rows if telemetry_rows is None else telemetry_rows
        self.history_days = settings.retention_history_days if history_days is None else history_days
        self._interval = settings.retention_interval_seconds if interval is None else interval
        self._enabled = settings.retention_enabled if enabled is None else enabled
        self._db: AsyncDB | None = None
        self._worker: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Retention sweep disabled (retention_enabled=false)")
            return
        if self._db is not None:
            return
        await self._ensure_db()
        self._running = True
        self._worker = asyncio.create_task(self._loop())
        logger.info(
            "Retention started (telemetry {}d / {} rows per parent, history {}d, every {}s)",
            self.telemetry_days,
            self.telemetry_rows,
            self.history_days,
            self._interval,
        )

    async def _ensure_db(self) -> AsyncDB:
        if self._db is None:
            if not is_postgres_dsn(self._db_path):
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = connect_backend(self._db_path)
            await self._db.connect()
        return self._db

    async def stop(self) -> None:
        self._running = False
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        if self._db is not None:
            db, self._db = self._db, None
            await db.close()

    async def _loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            if not self._running:
                return
            try:
                await self.run_once()
            except Exception as e:
                logger.warning("Retention sweep failed, next pass in {}s: {}", self._interval, e)

    async def run_once(self) -> dict[str, int]:
        """Sweep every policy this installation allows to delete, and say how much each one removed.

        Callable on a sweeper that was never started. The handle opens on first use and stays open, so
        overlapping passes serialise on one connection instead of fighting over the same file.
        """
        return await self._sweep(await self._ensure_db())

    async def _sweep(self, db: AsyncDB) -> dict[str, int]:
        dialect: Dialect = "postgresql" if db.dialect == "postgresql" else "sqlite"
        present = await _present_tables(db)
        removed: dict[str, int] = {}
        absent: list[str] = []
        for policy in POLICIES.values():
            check_identifiers(policy)
            days = self._days_for(policy)
            capped = self._is_capped(policy)
            if (days <= 0 and not capped) or policy.age_column is None:
                continue
            if policy.table not in present:
                absent.append(policy.table)
                continue
            async with db.transaction():
                deleted = await self._delete_older_than(db, policy, days, dialect) if days > 0 else 0
                if capped:
                    deleted += await self._cap_per_parent(db, policy, int(self.telemetry_rows))
            if deleted:
                removed[policy.table] = deleted
        if absent:
            logger.info("Retention skipped tables this install never created: {}", ", ".join(absent))
        if removed:
            logger.info("Retention removed {} rows: {}", sum(removed.values()), removed)
        return removed

    def _is_capped(self, policy: TablePolicy) -> bool:
        """Whether the per-parent row bound applies, independent of the age rule.

        `retention_telemetry_days=0` switches the age pass off and is documented to leave the cap running,
        so the two knobs cannot share one condition.
        """
        return policy.kind == "telemetry" and policy.parent_column is not None and self.telemetry_rows > 0

    def _days_for(self, policy: TablePolicy) -> float:
        match policy.kind:
            case "telemetry":
                return self.telemetry_days
            case "history":
                return self.history_days
            case _:
                return 0.0

    @staticmethod
    async def _delete_older_than(db: AsyncDB, policy: TablePolicy, days: float, dialect: Dialect) -> int:
        sql = f"DELETE FROM {policy.table} WHERE {policy.age_column} < ?"  # both names come from POLICIES, never from a caller  # nosec B608
        return int(await db.execute(sql, (cutoff(policy, days, dialect),)) or 0)

    @staticmethod
    async def _cap_per_parent(db: AsyncDB, policy: TablePolicy, keep: int) -> int:
        """Keep the newest `keep` rows per parent and drop the rest, oldest first."""
        parents = await db.fetchall(
            f"SELECT DISTINCT {policy.parent_column} AS parent FROM {policy.table}"  # name from POLICIES  # nosec B608
        )
        total = 0
        for row in parents:
            parent: Any = row["parent"]
            if parent is None:
                continue
            stale = await db.fetchall(
                f"SELECT {policy.id_column} AS id FROM {policy.table}"  # names from POLICIES  # nosec B608
                f" WHERE {policy.parent_column} = ? AND {policy.id_column} NOT IN ("
                f"SELECT {policy.id_column} FROM {policy.table}"  # names from POLICIES
                f" WHERE {policy.parent_column} = ?"
                f" ORDER BY {policy.age_column} DESC, {policy.id_column} DESC LIMIT ?)",  # names from POLICIES
                (parent, parent, keep),
            )
            ids = [entry["id"] for entry in stale]
            for start in range(0, len(ids), _DELETE_CHUNK):
                chunk = ids[start : start + _DELETE_CHUNK]
                marks = ", ".join("?" for _ in chunk)
                total += int(
                    await db.execute(
                        f"DELETE FROM {policy.table} WHERE {policy.id_column} IN ({marks})",  # ids travel bound  # nosec B608
                        chunk,
                    )
                    or 0
                )
        return total
