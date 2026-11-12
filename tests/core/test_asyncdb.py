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
        leaked = self._workers() - before
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
