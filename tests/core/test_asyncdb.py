import asyncio
import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from raven.core.asyncdb import (
    PostgresDB,
    SQLiteDB,
    connect_backend,
    is_postgres_dsn,
    is_postgres_url,
    normalize_dsn,
    postgres_dsn,
)


def test_is_postgres_url_plain_scheme():
    assert is_postgres_url("postgresql://user:pass@localhost:5432/raven")
    assert is_postgres_url("PostgreSQL://user@host/db")
    assert not is_postgres_url("data/raven.db")
    assert not is_postgres_url("")
    assert not is_postgres_url("sqlite:///data/raven.db")


def test_is_postgres_url_sqlalchemy_scheme():
    assert is_postgres_url("postgresql+asyncpg://user:pass@localhost:5432/raven_test")
    assert is_postgres_url("postgresql+psycopg://user@host/db")
    assert is_postgres_url("  postgresql+asyncpg://user@host/db  ")


def test_normalize_dsn_strips_driver_suffix():
    assert (
        normalize_dsn("postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
        == "postgresql://raven:raven@localhost:5432/raven_test"
    )
    assert (
        normalize_dsn("postgresql://raven:raven@localhost:5432/raven")
        == "postgresql://raven:raven@localhost:5432/raven"
    )


def test_postgres_dsn_prefers_normalized_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
    assert postgres_dsn() == "postgresql://raven:raven@localhost:5432/raven_test"


def test_postgres_dsn_empty_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert postgres_dsn() is None


def test_is_postgres_dsn_handles_sqlalchemy_scheme():
    assert is_postgres_dsn("postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
    assert not is_postgres_dsn("data/raven.db")


def test_connect_backend_uses_env_dsn(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://raven:raven@localhost:5432/raven_test")
    db = connect_backend("data/raven.db")
    assert isinstance(db, PostgresDB)
    assert db.dsn == "postgresql://raven:raven@localhost:5432/raven_test"


def test_connect_backend_uses_dsn_argument():
    db = connect_backend(dsn="postgresql+asyncpg://user@host:5432/raven")
    assert isinstance(db, PostgresDB)
    assert db.dsn == "postgresql://user@host:5432/raven"


def test_connect_backend_dsn_db_path():
    db = connect_backend("postgresql://user@host:5432/raven")
    assert isinstance(db, PostgresDB)


def test_connect_backend_sqlite_fallback():
    db = connect_backend("data/raven.db")
    assert isinstance(db, SQLiteDB)
    assert db._path == "data/raven.db"


def test_connect_backend_requires_path_without_dsn():
    with patch.dict("os.environ", {"DATABASE_URL": ""}, clear=True):
        try:
            connect_backend(None)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for missing db_path")


def _aiosqlite_workers() -> set[int]:
    """Live non-daemon aiosqlite worker threads: one per connection the process opened and did not close."""
    return {
        id(t)
        for t in threading.enumerate()
        if not t.daemon and getattr(getattr(t, "_target", None), "__qualname__", "") == "_connection_worker_thread"
    }


_WORKER_EXIT_TIMEOUT = 5.0
"""How long a worker gets to stop before the verdict calls it a leak — the same budget the session
reporter in `tests/conftest.py` gives one before it names the process as hung."""


class TestFailedOpenReleasesItsWorker:
    """`aiosqlite.connect()` starts a non-daemon worker thread, and that thread only stops when
    `close()` hands it the stop sentinel. A file that is not a database fails inside `_ensure`,
    before `self._conn` is assigned, so `close()` had nothing to close: the error reached the caller,
    the caller closed the store, and the interpreter still blocked forever in `threading._shutdown`.
    """

    def _corrupt(self, tmp_path: Path) -> Path:
        path = tmp_path / "not-a-database.db"
        path.write_bytes(b"this is not a sqlite file at all")
        return path

    def _workers(self) -> set[int]:
        return {
            id(t)
            for t in threading.enumerate()
            if not t.daemon and getattr(getattr(t, "_target", None), "__qualname__", "") == "_connection_worker_thread"
        }

    def _survivors(self, candidates: set[int]) -> set[int]:
        """Workers still alive once given the chance to stop.

        `close()` hands a worker its stop sentinel and returns; the thread's own exit is not part of that
        await, so reading `threading.enumerate()` on the next line measures scheduling, not cleanup. The
        session reporter in `tests/conftest.py` rules on a leak by joining first, and this test disagreed
        with it: red once in 8468 cases on a starved box, green in every run since. A worker the cleanup
        never told to stop is still red, after the whole timeout.
        """
        threads = [t for t in threading.enumerate() if id(t) in candidates]
        for thread in threads:
            thread.join(timeout=_WORKER_EXIT_TIMEOUT)
        return {id(thread) for thread in threads if thread.is_alive()}

    def _open(self, path: Path) -> None:
        async def _run() -> None:
            db = connect_backend(str(path))
            try:
                await db.fetchval("SELECT 1")
            finally:
                await db.close()

        asyncio.run(_run())

    def test_the_failure_still_reaches_the_caller(self, tmp_path: Path) -> None:
        with pytest.raises(sqlite3.DatabaseError):
            self._open(self._corrupt(tmp_path))

    def test_the_failed_open_leaves_no_worker_behind(self, tmp_path: Path) -> None:
        """The point of the cleanup: an error row in `raven doctor` must not hang the process."""
        before = self._workers()
        with pytest.raises(sqlite3.DatabaseError):
            self._open(self._corrupt(tmp_path))
        leaked = self._survivors(self._workers() - before)
        assert not leaked, f"{len(leaked)} aiosqlite worker(s) survived a failed open"

    def test_a_healthy_open_keeps_its_worker_until_closed(self, tmp_path: Path) -> None:
        """The negative control: the probe counts a real worker, so its verdict on the leak means
        something — and an ordinary close() is what stops it, not the new cleanup path."""
        path = tmp_path / "healthy.db"
        before = self._workers()

        async def _open_then_close() -> set[int]:
            db = connect_backend(str(path))
            await db.fetchval("SELECT 1")
            opened = self._workers() - before
            assert len(opened) == 1, "the probe cannot see an open connection, so its verdict means nothing"
            await db.close()
            for thread in threading.enumerate():
                if id(thread) in opened:
                    thread.join(timeout=5.0)
            return self._workers() & opened

        assert asyncio.run(_open_then_close()) == set()


class TestConcurrentOpensShareOneConnection:
    """`_ensure()` checked `_conn is None`, then awaited `aiosqlite.connect()` before assigning it.

    Two coroutines reaching an unopened handle therefore both opened a connection to the same file,
    and the second assignment dropped the first: the loser's WAL pragma answered `database is locked`
    inside its worker thread, and its non-daemon worker had no owner left to close it. `Database` in
    `raven/core/db.py` already serialises this with a connect lock; this handle has to as well.
    """

    def test_eight_concurrent_opens_leave_one_worker(self, tmp_path: Path) -> None:
        path = tmp_path / "shared.db"
        before = _aiosqlite_workers()

        async def _race() -> set[int]:
            db = connect_backend(str(path))
            await asyncio.gather(*(db.connect() for _ in range(8)))
            opened = _aiosqlite_workers() - before
            await db.close()
            for thread in threading.enumerate():
                if id(thread) in opened:
                    thread.join(timeout=5.0)
            assert not _aiosqlite_workers() & opened, "a connection the handle forgot to keep was never closed"
            return opened

        opened = asyncio.run(_race())
        assert len(opened) == 1, f"{len(opened)} connections opened for one handle"

    def test_the_statement_path_never_opens_a_second_connection(self, tmp_path: Path) -> None:
        """Statements already queue behind the writer gate, so the fix must not be needed there."""
        path = tmp_path / "shared-statements.db"
        before = _aiosqlite_workers()

        async def _race() -> int:
            db = connect_backend(str(path))
            values = await asyncio.gather(*(db.fetchval("SELECT 1") for _ in range(8)))
            assert values == [1] * 8, "the racing statements did not all reach a working connection"
            opened = _aiosqlite_workers() - before
            await db.close()
            for thread in threading.enumerate():
                if id(thread) in opened:
                    thread.join(timeout=5.0)
            return len(opened)

        assert asyncio.run(_race()) == 1, "the statement path opened more than one connection"

    def test_racing_opens_build_one_pool(self) -> None:
        """The Postgres handle has the same check-await-assign shape, so it gets the same lock."""
        asyncpg = pytest.importorskip("asyncpg")
        built: list[int] = []

        class FakePool:
            async def close(self) -> None:
                pass

        async def create_pool(*_args: object, **_kwargs: object) -> FakePool:
            built.append(1)
            await asyncio.sleep(0)
            return FakePool()

        async def _race() -> int:
            db = PostgresDB("postgresql://u:p@localhost:5432/raven")
            with patch.object(asyncpg, "create_pool", create_pool):
                await asyncio.gather(*(db.connect() for _ in range(8)))
            return len(built)

        assert asyncio.run(_race()) == 1, f"{len(built)} pools built for one handle"
