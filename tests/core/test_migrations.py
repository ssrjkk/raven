from __future__ import annotations

import aiosqlite
import pytest

from raven.core.asyncdb import SQLiteDB
from raven.core.migrations import _MIGRATIONS, Migrator


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "migrate.db"


@pytest.mark.asyncio
async def test_migration_3_creates_checkpoints_table(db_path):
    mig3 = next(m for m in _MIGRATIONS if m.version == 3)
    assert mig3.migrate_fn is not None
    db = SQLiteDB(db_path)
    await db.connect()
    await mig3.migrate_fn(db)
    await db.commit()
    row = await db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'")
    assert row is not None
    assert row[0] == "checkpoints"
    await db.close()


@pytest.mark.asyncio
async def test_migration_4_creates_routines_and_logs(db_path):
    mig4 = next(m for m in _MIGRATIONS if m.version == 4)
    assert mig4.migrate_fn is not None
    db = SQLiteDB(db_path)
    await db.connect()
    await mig4.migrate_fn(db)
    await db.commit()
    row = await db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='routines'")
    assert row is not None
    assert row[0] == "routines"
    row = await db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='routine_logs'")
    assert row is not None
    assert row[0] == "routine_logs"
    await db.close()


@pytest.mark.asyncio
async def test_migrator_runs_all_pending(db_path):
    m = Migrator(db_path)
    await m.migrate()
    conn = await aiosqlite.connect(str(db_path))
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'") as c:
        assert await c.fetchone() is not None
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routines'") as c:
        assert await c.fetchone() is not None
    await conn.close()


@pytest.mark.asyncio
async def test_migrator_idempotent(db_path):
    m = Migrator(db_path)
    await m.migrate()
    await m.migrate()
    conn = await aiosqlite.connect(str(db_path))
    async with conn.execute("SELECT COUNT(*) FROM _migrations") as c:
        row = await c.fetchone()
        assert row is not None
        assert row[0] >= 4
    await conn.close()
