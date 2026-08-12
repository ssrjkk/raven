from __future__ import annotations

import asyncio
import contextlib
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger


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

    async def connect(self) -> None:
        await self._ensure()

    async def _ensure(self) -> aiosqlite.Connection:
        if self._conn is None:
            connection = await aiosqlite.connect(self._path)
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

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int | None:
        conn = await self._ensure()
        cursor = await conn.execute(sql, tuple(params))
        return cursor.rowcount

    async def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        conn = await self._ensure()
        await conn.executemany(sql, [tuple(p) for p in seq_of_params])

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any | None:
        conn = await self._ensure()
        cursor = await conn.execute(sql, tuple(params))
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        conn = await self._ensure()
        cursor = await conn.execute(sql, tuple(params))
        try:
            rows = await cursor.fetchall()
            return list(rows)
        finally:
            await cursor.close()

    async def fetchval(self, sql: str, params: Sequence[Any] = ()) -> Any:
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
        conn = await self._ensure()
        await conn.executescript(sql)

    async def commit(self) -> None:
        conn = await self._ensure()
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @contextlib.asynccontextmanager
    async def transaction(self):
        conn = await self._ensure()
        await conn.execute("BEGIN")
        try:
            yield
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


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
        self._tx: Any = None

    @property
    def _p(self) -> Any:
        if self._pool is None:
            msg = "Postgres database not connected"
            raise RuntimeError(msg)
        return self._pool

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
        if self._tx is not None:
            return _rowcount(await self._tx.execute(rewritten, *args))
        async with self._p.acquire() as conn:
            return _rowcount(await conn.execute(rewritten, *args))

    async def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> None:
        rewritten, _ = self._rewrite(sql, seq_of_params[0] if seq_of_params else ())
        arglists = [tuple(p) for p in seq_of_params]
        if self._tx is not None:
            await self._tx.executemany(rewritten, arglists)
            return
        async with self._p.acquire() as conn:
            await conn.executemany(rewritten, arglists)

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Any | None:
        rewritten, args = self._rewrite(sql, params)
        if self._tx is not None:
            return await self._tx.fetchrow(rewritten, *args)
        async with self._p.acquire() as conn:
            return await conn.fetchrow(rewritten, *args)

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        rewritten, args = self._rewrite(sql, params)
        if self._tx is not None:
            return list(await self._tx.fetch(rewritten, *args))
        async with self._p.acquire() as conn:
            return list(await conn.fetch(rewritten, *args))

    async def fetchval(self, sql: str, params: Sequence[Any] = ()) -> Any:
        rewritten, args = self._rewrite(sql, params)
        if self._tx is not None:
            return await self._tx.fetchval(rewritten, *args)
        async with self._p.acquire() as conn:
            return await conn.fetchval(rewritten, *args)

    async def run_script(self, sql: str) -> None:
        if self._tx is not None:
            await self._tx.execute(sql)
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
    async def transaction(self):
        async with self._p.acquire() as conn:
            previous = self._tx
            self._tx = conn
            try:
                async with conn.transaction():
                    yield
            finally:
                self._tx = previous


def connect_backend(db_path: str | Path | None = None, dsn: str | None = None) -> AsyncDB:
    """Build a backend for the configured environment.

    Prefers Postgres when ``DATABASE_URL`` (or ``dsn`` / a ``postgresql://``
    ``db_path``) points at a ``postgresql://`` DSN; otherwise falls back to
    the SQLite file at ``db_path`` (required for the SQLite path).
    """
    path_str = str(db_path) if db_path is not None else ""
    candidate = dsn if dsn is not None else os.environ.get("DATABASE_URL", "")
    if candidate.startswith("postgresql://") or path_str.startswith("postgresql://"):
        return PostgresDB(candidate if candidate.startswith("postgresql://") else path_str)
    if db_path is None:
        msg = "db_path is required for the SQLite backend"
        raise ValueError(msg)
    return SQLiteDB(db_path)


def postgres_dsn() -> str | None:
    dsn = os.environ.get("DATABASE_URL", "")
    if dsn.startswith("postgresql://"):
        return dsn
    return None


def is_postgres_dsn(db_path: str | Path) -> bool:
    """True when a store ``db_path`` argument is a Postgres DSN string.

    DSNs must never be routed through ``pathlib`` (on Windows ``Path`` mangles
    ``//`` separators), so callers should branch on this before constructing a
    ``Path`` for the SQLite case.
    """
    return str(db_path).startswith("postgresql://")
