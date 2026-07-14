from __future__ import annotations

import aiosqlite
import pytest

from raven.core.migrations import _MIGRATIONS, Migrator


@pytest.fixture
async def tmp_db(tmp_path):
    db = tmp_path / "migrate.db"
    conn = await aiosqlite.connect(str(db))
    await conn.execute("PRAGMA journal_mode=WAL")
    yield db, conn
    await conn.close()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "migrate.db"


@pytest.mark.asyncio
async def test_migration_3_creates_checkpoints_table(tmp_db):
    db_path, conn = tmp_db
    mig3 = [m for m in _MIGRATIONS if m.version == 3][0]
    await mig3.migrate_fn(conn)
    await conn.commit()
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'") as c:
        row = await c.fetchone()
    assert row is not None
    assert row[0] == "checkpoints"


@pytest.mark.asyncio
async def test_migration_4_creates_routines_and_logs(tmp_db):
    db_path, conn = tmp_db
    mig4 = [m for m in _MIGRATIONS if m.version == 4][0]
    await mig4.migrate_fn(conn)
    await conn.commit()
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routines'") as c:
        row = await c.fetchone()
    assert row is not None
    assert row[0] == "routines"
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='routine_logs'") as c:
        row = await c.fetchone()
    assert row is not None
    assert row[0] == "routine_logs"


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
