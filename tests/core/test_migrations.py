from __future__ import annotations

import aiosqlite
import pytest

from raven.core.asyncdb import AsyncDB, SQLiteDB
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


@pytest.mark.asyncio
async def test_apply_pending_catches_a_migration_added_below_the_max(db_path):
    """A hotfix back-merged as an older version used to be skipped forever.

    Selecting on MAX(version) meant any registered version below the installed maximum never
    applied and never reported - the table simply lacked whatever it added.
    """
    from raven.core.migrations import Migration, apply_pending_migrations

    db = SQLiteDB(db_path)
    await db.connect()
    await db.execute("CREATE TABLE _migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP)")
    await db.execute("INSERT INTO _migrations (version) VALUES (1000)")  # what the old MAX would see
    await db.commit()

    ran: list[str] = []

    async def _noop(handle: AsyncDB) -> None:
        ran.append("back-merged")

    registered = list(_MIGRATIONS)
    _MIGRATIONS[:] = [Migration(0, "back-merged hotfix", None, _noop)]
    try:
        await apply_pending_migrations(db)
        applied = sorted(
            row["version"] for row in await db.fetchall("SELECT version FROM _migrations")
        )
    finally:
        _MIGRATIONS[:] = registered

    assert ran == ["back-merged"]
    assert applied == [0, 1000]
    await db.close()


def test_register_rejects_a_duplicate_version():
    from raven.core.migrations import register

    existing = next(m for m in _MIGRATIONS)
    with pytest.raises(ValueError, match="duplicate migration version"):

        @register(existing.version, "collides")
        async def _collision(db):  # pragma: no cover - registration fails first
            return None


@pytest.mark.asyncio
async def test_migrator_records_every_registered_version(db_path):
    m = Migrator(db_path)
    await m.migrate()
    conn = await aiosqlite.connect(str(db_path))
    async with conn.execute("SELECT version FROM _migrations") as cur:
        rows = await cur.fetchall()
    await conn.close()
    assert {r[0] for r in rows} >= {mig.version for mig in _MIGRATIONS}
