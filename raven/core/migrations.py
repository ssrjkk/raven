from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite
from loguru import logger

from raven.core.asyncdb import AsyncDB, SQLiteDB

MIGRATIONS_TABLE_SQLITE = (
    "CREATE TABLE IF NOT EXISTS _migrations "
    "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)
MIGRATIONS_TABLE_POSTGRES = (
    "CREATE TABLE IF NOT EXISTS _migrations "
    "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT NOW())"
)

MigrateFn = Callable[[AsyncDB], Awaitable[None]]


class Migration:
    def __init__(
        self,
        version: int,
        description: str,
        sql: str | None = None,
        migrate_fn: MigrateFn | None = None,
    ):
        self.version = version
        self.description = description
        self.sql = sql
        self.migrate_fn = migrate_fn


_MIGRATIONS: list[Migration] = []


def register(version: int, description: str, sql: str | None = None) -> Callable[[MigrateFn], MigrateFn]:
    def wrapper(fn: MigrateFn) -> MigrateFn:
        _MIGRATIONS.append(Migration(version, description, sql, fn))
        return fn

    return wrapper


async def _ensure_column(db: AsyncDB, table: str, ddl_sqlite: str, ddl_postgres: str) -> None:
    if db.dialect == "postgresql":
        await db.execute(ddl_postgres)
    else:
        try:
            await db.execute(ddl_sqlite)
        except aiosqlite.OperationalError:
            logger.debug("Migration: column already exists in {}", table)


@register(1, "Add agent_skills column to sessions")
async def _migration_1(db: AsyncDB):
    await _ensure_column(
        db,
        "sessions",
        "ALTER TABLE sessions ADD COLUMN agent_skills TEXT DEFAULT '[]'",
        "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS agent_skills TEXT DEFAULT '[]'",
    )


@register(2, "Add role column to users table")
async def _migration_2(db: AsyncDB):
    await _ensure_column(
        db,
        "users",
        "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'",
    )


@register(3, "Create checkpoints table")
async def _migration_3(db: AsyncDB):
    if db.dialect == "postgresql":
        await db.run_script(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                messages TEXT NOT NULL DEFAULT '[]',
                agent_state TEXT NOT NULL DEFAULT '{}',
                created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
            )
            """
        )
    else:
        await db.run_script(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT '',
                messages TEXT NOT NULL DEFAULT '[]',
                agent_state TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


@register(4, "Create routines table")
async def _migration_4(db: AsyncDB):
    if db.dialect == "postgresql":
        await db.run_script(
            """
            CREATE TABLE IF NOT EXISTS routines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                trigger TEXT NOT NULL DEFAULT 'manual',
                schedule TEXT NOT NULL DEFAULT '08:00',
                status TEXT NOT NULL DEFAULT 'active',
                user_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                last_run_status TEXT,
                last_run_at DOUBLE PRECISION,
                config TEXT NOT NULL DEFAULT '{}',
                created_at DOUBLE PRECISION
            );
            CREATE TABLE IF NOT EXISTS routine_logs (
                id TEXT PRIMARY KEY,
                routine_id TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                duration_ms DOUBLE PRECISION,
                created_at DOUBLE PRECISION NOT NULL
            )
            """
        )
    else:
        await db.run_script(
            """
            CREATE TABLE IF NOT EXISTS routines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                action TEXT NOT NULL,
                trigger TEXT NOT NULL DEFAULT 'manual',
                schedule TEXT NOT NULL DEFAULT '08:00',
                status TEXT NOT NULL DEFAULT 'active',
                user_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                last_run_status TEXT,
                last_run_at REAL,
                config TEXT NOT NULL DEFAULT '{}',
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS routine_logs (
                id TEXT PRIMARY KEY,
                routine_id TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                duration_ms REAL,
                created_at REAL NOT NULL
            )
            """
        )


@register(5, "Add indexes on core tables")
async def _migration_5(db: AsyncDB):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_channel ON sessions(channel)",
        "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_channel ON users(channel)",
        "CREATE INDEX IF NOT EXISTS idx_users_external_id ON users(external_id)",
    ]
    for idx in indexes:
        if db.dialect == "postgresql":
            await db.execute(idx)
        else:
            try:
                await db.execute(idx)
            except aiosqlite.OperationalError:
                logger.debug("Migration 5: index already exists")


@register(6, "Create monitors + monitor_checks tables")
async def _migration_6(db: AsyncDB):
    if db.dialect == "postgresql":
        await db.run_script(
            """
            CREATE TABLE IF NOT EXISTS monitors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('price','http','rss','file','process')),
                config TEXT NOT NULL DEFAULT '{}',
                condition TEXT NOT NULL DEFAULT '',
                cooldown_minutes INTEGER NOT NULL DEFAULT 30,
                interval_seconds INTEGER NOT NULL DEFAULT 300,
                notify_channels TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','error')),
                user_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                last_checked DOUBLE PRECISION,
                last_triggered DOUBLE PRECISION,
                created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
            );
            CREATE TABLE IF NOT EXISTS monitor_checks (
                id BIGSERIAL PRIMARY KEY,
                monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                checked_at DOUBLE PRECISION NOT NULL,
                response_time_ms DOUBLE PRECISION,
                triggered INTEGER DEFAULT 0,
                result TEXT,
                error TEXT
            )
            """
        )
    else:
        await db.run_script(
            """
            CREATE TABLE IF NOT EXISTS monitors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('price','http','rss','file','process')),
                config TEXT NOT NULL DEFAULT '{}',
                condition TEXT NOT NULL DEFAULT '',
                cooldown_minutes INTEGER NOT NULL DEFAULT 30,
                interval_seconds INTEGER NOT NULL DEFAULT 300,
                notify_channels TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','error')),
                user_id TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                last_checked TEXT,
                last_triggered TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS monitor_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id TEXT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                checked_at REAL NOT NULL,
                response_time_ms REAL,
                triggered INTEGER DEFAULT 0,
                result TEXT,
                error TEXT
            )
            """
        )
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_monitor_status ON monitors(status)",
        "CREATE INDEX IF NOT EXISTS idx_monitor_user_id ON monitors(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_monitor_checks_monitor_id ON monitor_checks(monitor_id)",
    ]
    for idx in indexes:
        if db.dialect == "postgresql":
            await db.execute(idx)
        else:
            try:
                await db.execute(idx)
            except aiosqlite.OperationalError:
                logger.debug("Migration 6: index already exists")


@register(7, "Create tasks + task_steps tables")
async def _migration_7(db: AsyncDB):
    await db.run_script(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL,
            plan_summary TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 1,
            current_step_index INTEGER NOT NULL DEFAULT 0,
            result TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            scheduled_at REAL,
            metadata TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS task_steps (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            step_order INTEGER NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tool TEXT NOT NULL DEFAULT '',
            params TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT,
            error TEXT,
            started_at REAL,
            completed_at REAL
        )
        """
    )
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_task_steps_task_id ON task_steps(task_id)",
        "CREATE INDEX IF NOT EXISTS idx_task_steps_status ON task_steps(status)",
    ]
    for idx in indexes:
        if db.dialect == "postgresql":
            await db.execute(idx)
        else:
            try:
                await db.execute(idx)
            except aiosqlite.OperationalError:
                logger.debug("Migration 7: index already exists")


@register(8, "Create coding_sessions table")
async def _migration_8(db: AsyncDB):
    await db.run_script(
        """
        CREATE TABLE IF NOT EXISTS coding_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            goal TEXT NOT NULL,
            project_path TEXT NOT NULL DEFAULT '',
            files TEXT DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            history TEXT DEFAULT '[]',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_cs_user ON coding_sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_cs_status ON coding_sessions(status)",
    ]
    for idx in indexes:
        if db.dialect == "postgresql":
            await db.execute(idx)
        else:
            try:
                await db.execute(idx)
            except aiosqlite.OperationalError:
                logger.debug("Migration 8: index already exists")


@register(9, "Add user_id + channel columns to monitors")
async def _migration_9(db: AsyncDB):
    if db.dialect == "postgresql":
        await _ensure_column(
            db,
            "monitors",
            "",
            "ALTER TABLE monitors ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT ''",
        )
        await _ensure_column(
            db,
            "monitors",
            "",
            "ALTER TABLE monitors ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT ''",
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_monitor_user_id ON monitors(user_id)")
    else:
        for col, ddl in (
            ("user_id", "ALTER TABLE monitors ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"),
            ("channel", "ALTER TABLE monitors ADD COLUMN channel TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                await db.execute(ddl)
            except aiosqlite.OperationalError:
                logger.debug("Migration 9: column {} already exists", col)
        try:
            await db.execute("CREATE INDEX IF NOT EXISTS idx_monitor_user_id ON monitors(user_id)")
        except aiosqlite.OperationalError:
            logger.debug("Migration 9: index already exists")


async def apply_pending_migrations(db: AsyncDB) -> None:
    table = MIGRATIONS_TABLE_POSTGRES if db.dialect == "postgresql" else MIGRATIONS_TABLE_SQLITE
    await db.execute(table)
    current = await db.fetchval("SELECT COALESCE(MAX(version), 0) FROM _migrations") or 0

    pending = sorted([m for m in _MIGRATIONS if m.version > current], key=lambda m: m.version)
    if not pending:
        return

    async with db.transaction():
        for mig in pending:
            logger.info("Applying migration {}: {}", mig.version, mig.description)
            try:
                if mig.sql:
                    await db.run_script(mig.sql)
                if mig.migrate_fn:
                    await mig.migrate_fn(db)
                await db.execute("INSERT INTO _migrations (version) VALUES (?)", (mig.version,))
                logger.info("Migration {} applied", mig.version)
            except Exception as e:
                logger.error("Migration {} failed: {}", mig.version, e)
                raise


class Migrator:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def get_current_version(self):
        db = SQLiteDB(self.db_path)
        try:
            await db.execute(MIGRATIONS_TABLE_SQLITE)
            current = await db.fetchval("SELECT COALESCE(MAX(version), 0) FROM _migrations") or 0
            return int(current)
        finally:
            await db.close()

    async def migrate(self, target: int | None = None):
        current = await self.get_current_version()
        pending = sorted([m for m in _MIGRATIONS if m.version > current], key=lambda m: m.version)
        if target:
            pending = [m for m in pending if m.version <= target]

        if not pending:
            logger.info("DB is up-to-date (version {})", current)
            return

        db = SQLiteDB(self.db_path)
        try:
            async with db.transaction():
                for mig in pending:
                    logger.info("Applying migration {}: {}", mig.version, mig.description)
                    try:
                        if mig.sql:
                            await db.run_script(mig.sql)
                        if mig.migrate_fn:
                            await mig.migrate_fn(db)
                        await db.execute("INSERT INTO _migrations (version) VALUES (?)", (mig.version,))
                        logger.info("Migration {} applied", mig.version)
                    except Exception as e:
                        logger.error("Migration {} failed: {}", mig.version, e)
                        raise
        finally:
            await db.close()

        logger.info("DB migrated to version {}", current + len(pending))

    def list_pending(self) -> list[Migration]:
        return sorted([m for m in _MIGRATIONS], key=lambda m: m.version)
