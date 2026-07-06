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
