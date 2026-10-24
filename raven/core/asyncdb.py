from __future__ import annotations

import asyncio
import contextlib
import contextvars
import itertools
import os
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

_handle_seq = itertools.count()


class AsyncDB(ABC):
    """Dialect-agnostic async database handle.

    Rows returned by fetchone/fetchall support both ``row["col"]`` and
    ``dict(row)`` access regardless of backend (aiosqlite.Row / asyncpg.Record).
    SQL uses ``?`` placeholders; the Postgres backend rewrites them to ``$n``.
    """

    dialect: str

    @abstractmethod
    async def connect(self) -> None:
        """Ensure the backend is connected (no-op for lazy backends)."""

    @abstractmethod
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int | None:
        """Execute a statement. Returns affected row count when known."""

    @abstractmethod
    async def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None: ...

    @abstractmethod
    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any | None: ...

    @abstractmethod
    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]: ...

    @abstractmethod
    async def fetchval(self, sql: str, params: Sequence[Any] = ()) -> Any: ...

    @abstractmethod
    async def run_script(self, sql: str) -> None:
        """Run a multi-statement DDL/script."""

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Run the enclosed statements atomically."""


class SQLiteDB(AsyncDB):
    dialect = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self._write_gate = asyncio.Lock()
        self._tx_owner: asyncio.Task[Any] | None = None
        self._tx_depth = 0

    async def connect(self) -> None:
        await self._ensure()

    async def _ensure(self) -> aiosqlite.Connection:
        if self._conn is None:
            # isolation_level=None gives each statement its own transaction, so a write is durable
            # the moment it runs instead of waiting for whichever caller reaches commit() first -
            # and no stale implicit transaction can make a later BEGIN fail. Grouped writes use
            # transaction(), which still issues an explicit BEGIN.
            connection = await aiosqlite.connect(self._path, isolation_level=None)
            connection.row_factory = aiosqlite.Row
            for pragma in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA busy_timeout=5000",
                "PRAGMA foreign_keys=ON",
            ):
                async with connection.execute(pragma):
                    pass
            self._conn = connection
        return self._conn

    @contextlib.asynccontextmanager
    async def _writer(self) -> AsyncIterator[None]:
        """Serialise every statement against an in-flight transaction.

        One SQLite connection carries one transaction, so a statement issued by another task while
        a ``transaction()`` is open would join it, read its uncommitted rows, and its ``commit()``
        would end it halfway. The owner passes through (it already holds the gate); everyone else
        waits. A transaction body therefore must not await DB work belonging to a *different* task.
        """
        if self._tx_owner is asyncio.current_task():
            yield
            return
        async with self._write_gate:
            yield

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int | None:
        async with self._writer():
            conn = await self._ensure()
            cursor = await conn.execute(sql, tuple(params))
            return cursor.rowcount

    async def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        rows = [tuple(p) for p in seq_of_params]
        if not rows:
            return
        async with self._writer():
            conn = await self._ensure()
            if self._tx_depth:
                await conn.executemany(sql, rows)
                return
            # autocommit would commit per row; a batch is one transaction (and the caller
            # holding a transaction above is already inside one).
            await conn.execute("BEGIN IMMEDIATE")
            try:
                await conn.executemany(sql, rows)
            except BaseException:
                await conn.rollback()
                raise
            await conn.commit()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any | None:
        async with self._writer():
            conn = await self._ensure()
            cursor = await conn.execute(sql, tuple(params))
            try:
                return await cursor.fetchone()
            finally:
                await cursor.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        async with self._writer():
            conn = await self._ensure()
            cursor = await conn.execute(sql, tuple(params))
            try:
                rows = await cursor.fetchall()
                return list(rows)
            finally:
                await cursor.close()

    async def fetchval(self, sql: str, params: Sequence[Any] = ()) -> Any:
        async with self._writer():
            conn = await self._ensure()
            cursor = await conn.execute(sql, tuple(params))
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
            if row is None:
                return None
            return row[0]

    async def run_script(self, sql: str) -> None:
        async with self._writer():
            conn = await self._ensure()
            if self._tx_depth == 0:
                await conn.executescript(sql)
                return
            # executescript commits whatever transaction is open before running, so inside a
            # transaction the script is cut with SQLite's own parser and run one statement at a
            # time - complete_statement() keeps quoted semicolons and triggers in one piece.
            buffer = ""
            for part in sql.split(";"):
                buffer += part + ";"
                if sqlite3.complete_statement(buffer):
                    await conn.execute(buffer)
                    buffer = ""
            if buffer.strip():
                await conn.execute(buffer)

    async def commit(self) -> None:
        async with self._writer():
            if self._tx_depth:
                return
            conn = await self._ensure()
            await conn.commit()

    async def close(self) -> None:
        async with self._writer():
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        current = asyncio.current_task()
        if self._tx_owner is current:
            name = f"raven_sp_{self._tx_depth}"
            conn = await self._ensure()
            await conn.execute(f"SAVEPOINT {name}")
            self._tx_depth += 1
            try:
                yield
            except BaseException:
                self._tx_depth -= 1
                await conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
                raise
            self._tx_depth -= 1
            await conn.execute(f"RELEASE SAVEPOINT {name}")
            return
        await self._write_gate.acquire()
        self._tx_owner = current
        self._tx_depth = 1
        try:
            conn = await self._ensure()
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                await conn.rollback()
                raise
            else:
                await conn.commit()
        finally:
            self._tx_depth = 0
            self._tx_owner = None
            self._write_gate.release()


def _rowcount(status: str) -> int | None:
    """Parse asyncpg's command status (e.g. ``UPDATE 3``) into a row count."""
    parts = status.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return None


class PostgresDB(AsyncDB):
    dialect = "postgresql"

    _MAX_CONNECT_RETRIES = 3
    _CONNECT_RETRY_DELAY_S = 2.0

    def __init__(self, dsn: str | None = None, pool: Any | None = None) -> None:
        self.dsn = dsn
        self._pool: Any = pool
        self._owns_pool = pool is None
        # The open transaction belongs to the caller that opened it, not to the handle: as
        # instance state it leaked into every other task's execute(), which then ran inside a
        # foreign transaction and was rolled back when that transaction failed.
        self._tx: contextvars.ContextVar[Any] = contextvars.ContextVar(
            f"raven_pg_tx_{next(_handle_seq)}", default=None
        )

    @property
    def _p(self) -> Any:
        if self._pool is None:
            msg = "Postgres database not connected"
            raise RuntimeError(msg)
        return self._pool

    @property
    def _tx_conn(self) -> Any:
        return self._tx.get()

    async def connect(self) -> None:
        if self._pool is not None:
            return
        import asyncpg

        last_error: Exception | None = None
        for attempt in range(1, self._MAX_CONNECT_RETRIES + 1):
            try:
                self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
                return
            except (TimeoutError, OSError, asyncpg.PostgresError) as e:
                last_error = e
                if attempt < self._MAX_CONNECT_RETRIES:
                    logger.warning(
                        "Postgres connect attempt {}/{} failed: {} — retrying in {}s",
                        attempt,
                        self._MAX_CONNECT_RETRIES,
                        e,
                        self._CONNECT_RETRY_DELAY_S,
                    )
                    await asyncio.sleep(self._CONNECT_RETRY_DELAY_S)
        msg = f"Postgres connect failed after {self._MAX_CONNECT_RETRIES} attempts"
        raise RuntimeError(msg) from last_error

    @staticmethod
    def _rewrite(sql: str, params: Sequence[Any]) -> tuple[str, list[Any]]:
        if not params:
            return sql, []
        parts = sql.split("?")
        if len(parts) - 1 != len(params):
            msg = f"placeholder count ({len(parts) - 1}) does not match param count ({len(params)})"
            raise ValueError(msg)
        out = parts[0]
        args: list[Any] = []
        for i, part in enumerate(parts[1:], start=1):
            args.append(params[i - 1])
            out += f"${i}" + part
        return out, args

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int | None:
        rewritten, args = self._rewrite(sql, params)
        tx = self._tx_conn
        if tx is not None:
            return _rowcount(await tx.execute(rewritten, *args))
        async with self._p.acquire() as conn:
            return _rowcount(await conn.execute(rewritten, *args))

    async def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        rewritten, _ = self._rewrite(sql, seq_of_params[0] if seq_of_params else ())
        arglists = [tuple(p) for p in seq_of_params]
        tx = self._tx_conn
        if tx is not None:
            await tx.executemany(rewritten, arglists)
            return
        async with self._p.acquire() as conn:
            await conn.executemany(rewritten, arglists)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any | None:
        rewritten, args = self._rewrite(sql, params)
        tx = self._tx_conn
        if tx is not None:
            return await tx.fetchrow(rewritten, *args)
        async with self._p.acquire() as conn:
            return await conn.fetchrow(rewritten, *args)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        rewritten, args = self._rewrite(sql, params)
        tx = self._tx_conn
        if tx is not None:
            return list(await tx.fetch(rewritten, *args))
        async with self._p.acquire() as conn:
            return list(await conn.fetch(rewritten, *args))

    async def fetchval(self, sql: str, params: Sequence[Any] = ()) -> Any:
        rewritten, args = self._rewrite(sql, params)
        tx = self._tx_conn
        if tx is not None:
            return await tx.fetchval(rewritten, *args)
        async with self._p.acquire() as conn:
            return await conn.fetchval(rewritten, *args)

    async def run_script(self, sql: str) -> None:
        tx = self._tx_conn
        if tx is not None:
            await tx.execute(sql)
            return
        async with self._p.acquire() as conn:
            await conn.execute(sql)

    async def commit(self) -> None:
        return

    async def close(self) -> None:
        if self._owns_pool and self._pool is not None:
            await self._pool.close()
        self._pool = None

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        ambient = self._tx_conn
        if ambient is not None:
            # asyncpg turns a transaction opened on a connection that already has one into a
            # savepoint, and the statements of this task keep using that same connection.
            async with ambient.transaction():
                yield
            return
        async with self._p.acquire() as conn:
            token = self._tx.set(conn)
            try:
                async with conn.transaction():
                    yield
            finally:
                self._tx.reset(token)


def is_postgres_url(value: str) -> bool:
    """True for ``postgresql://`` and SQLAlchemy-style ``postgresql+<driver>://`` DSNs."""
    v = value.strip().lower()
    return v.startswith("postgresql://") or v.startswith("postgresql+")


def normalize_dsn(value: str) -> str:
    """Strip the SQLAlchemy ``+<driver>`` suffix so asyncpg accepts the URL."""
    scheme, sep, rest = value.strip().partition("://")
    if scheme.startswith("postgresql+"):
        scheme = "postgresql"
    return f"{scheme}{sep}{rest}"


def connect_backend(db_path: str | Path | None = None, dsn: str | None = None) -> AsyncDB:
    """Build a backend for the configured environment.

    Prefers Postgres when ``DATABASE_URL`` (or ``dsn`` / a ``postgresql://``
    ``db_path``) points at a ``postgresql://`` DSN; otherwise falls back to
    the SQLite file at ``db_path`` (required for the SQLite path).
    """
    path_str = str(db_path) if db_path is not None else ""
    candidate = dsn if dsn is not None else os.environ.get("DATABASE_URL", "")
    if is_postgres_url(candidate) or is_postgres_url(path_str):
        pg_dsn = candidate if is_postgres_url(candidate) else path_str
        return PostgresDB(normalize_dsn(pg_dsn))
    if db_path is None:
        msg = "db_path is required for the SQLite backend"
        raise ValueError(msg)
    return SQLiteDB(db_path)


def postgres_dsn() -> str | None:
    dsn = os.environ.get("DATABASE_URL", "")
    if is_postgres_url(dsn):
        return normalize_dsn(dsn)
    return None


def is_postgres_dsn(db_path: str | Path) -> bool:
    """True when a store ``db_path`` argument is a Postgres DSN string.

    DSNs must never be routed through ``pathlib`` (on Windows ``Path`` mangles
    ``//`` separators), so callers should branch on this before constructing a
    ``Path`` for the SQLite case.
    """
    return is_postgres_url(str(db_path))
