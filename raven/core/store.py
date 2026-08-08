from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from raven.core.migrations import apply_pending_migrations


class BaseStore:
    SCHEMA: str = ""

    def __init__(self, db_path: str | Path):
        self._path = str(db_path)
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._schema_ensured = False

    async def _conn(self) -> aiosqlite.Connection:
        if self._connection is None:
            self._connection = await aiosqlite.connect(self._path)
            self._connection.row_factory = aiosqlite.Row
            for pragma in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA busy_timeout=5000",
                "PRAGMA foreign_keys=ON",
            ):
                async with self._connection.execute(pragma):
                    pass
        if not self._schema_ensured:
            async with self._lock:
                if not self._schema_ensured:
                    await self._connection.executescript(self.SCHEMA)
                    await apply_pending_migrations(self._connection)
                    await self._post_schema(self._connection)
                    await self._connection.commit()
                    self._schema_ensured = True
                    logger.info("Schema initialized for {}", type(self).__name__)
        return self._connection

    async def _post_schema(self, connection: aiosqlite.Connection) -> None:
        """Hook for stores that need column migrations after schema creation."""

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
                logger.debug("Connection closed for {}", type(self).__name__)

    async def _execute(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        conn = await self._conn()
        return await conn.execute(sql, params)

    async def _fetchone(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        cursor = await self._execute(sql, params)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def _fetchall(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        cursor = await self._execute(sql, params)
        try:
            rows = await cursor.fetchall()
            return list(rows)
        finally:
            await cursor.close()

    async def _commit(self) -> None:
        conn = await self._conn()
        await conn.commit()

    async def _execute_many(self, sql: str, params_list: list[list[Any] | tuple[Any, ...]]) -> None:
        conn = await self._conn()
        for params in params_list:
            await conn.execute(sql, params)
