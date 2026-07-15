from __future__ import annotations

from pathlib import Path

from loguru import logger

MIGRATIONS_TABLE = "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"


class Migration:
    def __init__(self, version: int, description: str, sql: str | None = None, migrate_fn=None):
        self.version = version
        self.description = description
        self.sql = sql
        self.migrate_fn = migrate_fn


_MIGRATIONS: list[Migration] = []


def register(version: int, description: str, sql: str | None = None):
    def wrapper(fn=None):
        m = Migration(version, description, sql, fn)
        _MIGRATIONS.append(m)
        return fn

    return wrapper


@register(1, "Add agent_skills column to sessions")
async def _migration_1(conn):
    try:
        await conn.execute("ALTER TABLE sessions ADD COLUMN agent_skills TEXT DEFAULT '[]'")
    except Exception:
        logger.debug("Migration 1: column already exists")


@register(2, "Add role column to users table")
async def _migration_2(conn):
    try:
        await conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    except Exception:
        logger.debug("Migration 2: column already exists")


@register(3, "Create checkpoints table")
async def _migration_3(conn):
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT '',
            messages TEXT NOT NULL DEFAULT '[]',
            agent_state TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


@register(4, "Create routines table")
async def _migration_4(conn):
    await conn.execute("""
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
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS routine_logs (
            id TEXT PRIMARY KEY,
            routine_id TEXT NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            duration_ms REAL,
            created_at REAL NOT NULL
        )
    """)


@register(5, "Add indexes on core tables")
async def _migration_5(conn):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_sessions_channel ON sessions(channel)",
        "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_channel ON users(channel)",
        "CREATE INDEX IF NOT EXISTS idx_users_external_id ON users(external_id)",
    ]
    for idx in indexes:
        try:
            await conn.execute(idx)
        except Exception:
            logger.debug("Migration 5: index already exists")


class Migrator:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def get_current_version(self):
        import aiosqlite

        conn = await aiosqlite.connect(str(self.db_path))
        try:
            await conn.execute(MIGRATIONS_TABLE)
            await conn.commit()
            async with conn.execute("SELECT COALESCE(MAX(version), 0) FROM _migrations") as c:
                row = await c.fetchone()
                return row[0] if row else 0
        finally:
            await conn.close()

    async def migrate(self, target: int | None = None):
        import aiosqlite

        current = await self.get_current_version()
        pending = sorted([m for m in _MIGRATIONS if m.version > current], key=lambda m: m.version)
        if target:
            pending = [m for m in pending if m.version <= target]

        if not pending:
            logger.info("DB is up-to-date (version {})", current)
            return

        conn = await aiosqlite.connect(str(self.db_path))
        try:
            await conn.execute("PRAGMA foreign_keys=OFF")
            for mig in pending:
                logger.info("Applying migration {}: {}", mig.version, mig.description)
                try:
                    if mig.sql:
                        await conn.executescript(mig.sql)
                    if mig.migrate_fn:
                        await mig.migrate_fn(conn)
                    await conn.execute("INSERT INTO _migrations (version) VALUES (?)", (mig.version,))
                    await conn.commit()
                    logger.info("Migration {} applied", mig.version)
                except Exception as e:
                    await conn.rollback()
                    logger.error("Migration {} failed: {}", mig.version, e)
                    raise
            await conn.execute("PRAGMA foreign_keys=ON")
        finally:
            await conn.close()

        logger.info("DB migrated to version {}", current + len(pending))

    def list_pending(self) -> list[Migration]:
        return sorted([m for m in _MIGRATIONS], key=lambda m: m.version)
