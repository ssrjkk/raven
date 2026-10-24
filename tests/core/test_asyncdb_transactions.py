"""AsyncDB transaction ownership: one connection, many callers, no cross-contamination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from raven.core.asyncdb import SQLiteDB

_SCHEMA = (
    "CREATE TABLE a (v TEXT);"
    "CREATE TABLE b (v TEXT);"
    "INSERT INTO a VALUES ('keep');"
    "INSERT INTO b VALUES ('keep');"
)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[SQLiteDB]:
    handle = SQLiteDB(tmp_path / "tx.db")
    await handle.connect()
    await handle.run_script(_SCHEMA)
    try:
        yield handle
    finally:
        await handle.close()


async def test_concurrent_transactions_serialise_instead_of_crashing(db: SQLiteDB) -> None:
    held = asyncio.Event()
    order: list[str] = []

    async def pass_a() -> None:
        async with db.transaction():
            order.append("a:begin")
            held.set()
            await asyncio.sleep(0.05)
            await db.execute("INSERT INTO b VALUES ('from-a')")
            order.append("a:end")

    async def pass_b() -> None:
        await held.wait()
        async with db.transaction():
            order.append("b:begin")
            await db.execute("INSERT INTO b VALUES ('from-b')")
            order.append("b:end")

    await asyncio.gather(pass_a(), pass_b())

    assert order == ["a:begin", "a:end", "b:begin", "b:end"]
    rows = await db.fetchall("SELECT v FROM b ORDER BY v")
    assert [r["v"] for r in rows] == ["from-a", "from-b", "keep"]


async def test_bystander_commit_cannot_end_a_foreign_transaction(db: SQLiteDB) -> None:
    inside = asyncio.Event()

    async def victim() -> None:
        async with db.transaction():
            await db.execute("DELETE FROM a")
            inside.set()
            await asyncio.sleep(0.1)  # a foreign write queues behind this transaction
            raise RuntimeError("database is locked")

    async def bystander() -> None:
        await inside.wait()
        await db.execute("INSERT INTO a VALUES ('bystander')")
        await db.commit()

    results = await asyncio.gather(victim(), bystander(), return_exceptions=True)
    assert isinstance(results[0], RuntimeError)

    # the victim rolls back only its own DELETE, and the bystander's write is its own unit
    rows = await db.fetchall("SELECT v FROM a ORDER BY v")
    assert [r["v"] for r in rows] == ["bystander", "keep"]


async def test_read_during_a_foreign_transaction_sees_committed_state(db: SQLiteDB) -> None:
    inside = asyncio.Event()
    settle = asyncio.Event()

    async def victim() -> None:
        async with db.transaction():
            await db.execute("DELETE FROM a")
            inside.set()
            await settle.wait()
            raise RuntimeError("database is locked")

    async def reader() -> list[str]:
        await inside.wait()
        settle.set()                      # let the transaction fail; the read must still wait
        rows = await db.fetchall("SELECT v FROM a")
        return [r["v"] for r in rows]

    results = await asyncio.gather(victim(), reader(), return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
    assert results[1] == ["keep"]


async def test_run_script_rolls_back_with_its_transaction(db: SQLiteDB) -> None:
    with pytest.raises(RuntimeError):
        async with db.transaction():
            await db.run_script("CREATE TABLE late (v TEXT);")
            raise RuntimeError("migration failed")

    created = await db.fetchone("SELECT name FROM sqlite_master WHERE name = 'late'")
    assert created is None


async def test_run_script_still_applies_multi_statement_scripts(db: SQLiteDB) -> None:
    """The statement splitter has to keep quoted semicolons and trigger bodies in one piece."""
    async with db.transaction():
        await db.run_script(
            "CREATE TABLE t1 (v TEXT DEFAULT 'a;b'); CREATE TABLE t2 (v TEXT);"
            "CREATE TRIGGER tr AFTER INSERT ON t2 BEGIN INSERT INTO t1 (v) VALUES ('trg'); END;"
        )
    names = {r["name"] for r in await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"t1", "t2"} <= names

    await db.execute("INSERT INTO t2 VALUES (1)")
    await db.execute("INSERT INTO t1 DEFAULT VALUES")
    assert sorted(r["v"] for r in await db.fetchall("SELECT v FROM t1")) == ["a;b", "trg"]


async def test_nested_transaction_is_a_savepoint(db: SQLiteDB) -> None:
    async with db.transaction():
        await db.execute("INSERT INTO a VALUES ('outer')")
        with pytest.raises(RuntimeError):
            async with db.transaction():
                await db.execute("INSERT INTO a VALUES ('inner')")
                raise RuntimeError("inner failed")
    rows = await db.fetchall("SELECT v FROM a ORDER BY v")
    assert [r["v"] for r in rows] == ["keep", "outer"]


async def test_write_without_commit_is_durable_to_a_second_connection(tmp_path: Path) -> None:
    """sqlite3 would otherwise park the row in an implicit transaction until some other caller
    reached commit(), and Python 3.12 rolls pending work back when the connection closes."""
    path = tmp_path / "durability.db"
    writer = SQLiteDB(path)
    await writer.connect()
    await writer.run_script("CREATE TABLE t (v TEXT)")
    await writer.execute("INSERT INTO t VALUES ('row')")

    reader = SQLiteDB(path)
    await reader.connect()
    try:
        rows = await reader.fetchall("SELECT v FROM t")
        assert [r["v"] for r in rows] == ["row"]
    finally:
        await reader.close()
    await writer.close()

    after = SQLiteDB(path)
    await after.connect()
    try:
        assert await after.fetchval("SELECT COUNT(*) FROM t") == 1
    finally:
        await after.close()


async def test_executemany_persists_every_row(db: SQLiteDB) -> None:
    await db.executemany("INSERT INTO a VALUES (?)", [("x",), ("y",)])
    rows = await db.fetchall("SELECT v FROM a ORDER BY v")
    assert [r["v"] for r in rows] == ["keep", "x", "y"]
