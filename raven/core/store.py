from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.asyncdb import AsyncDB, connect_backend
from raven.core.migrations import apply_pending_migrations


class BaseStore:
    SCHEMA: str = ""
    SCHEMA_POSTGRES: str = ""

    def __init__(self, db_path: str | Path | AsyncDB):
        if isinstance(db_path, AsyncDB):
            self._db = db_path
            self._path: str | None = None
        else:
            self._db = connect_backend(db_path)
            self._path = str(db_path)
        self._lock = asyncio.Lock()
        self._connected = False
        self._schema_ensured = False

    async def _dialect_schema(self) -> str:
        if self._db.dialect == "postgresql" and self.SCHEMA_POSTGRES:
            return self.SCHEMA_POSTGRES
        return self.SCHEMA

    async def _conn(self) -> AsyncDB:
        async with self._lock:
            if not self._connected:
                await self._db.connect()
                self._connected = True
            if not self._schema_ensured:
                await self._db.run_script(await self._dialect_schema())
                await apply_pending_migrations(self._db)
                await self._post_schema(self._db)
                await self._db.commit()
                self._schema_ensured = True
                logger.info("Schema initialized for {}", type(self).__name__)
            return self._db

    async def _post_schema(self, connection: AsyncDB) -> None:
        """Hook for stores that need column migrations after schema creation."""

    async def close(self) -> None:
        async with self._lock:
            await self._db.close()
            self._connected = False
            logger.debug("Connection closed for {}", type(self).__name__)

    async def _execute(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> int | None:
        db = await self._conn()
        return await db.execute(sql, params)

    async def _fetchone(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> Any | None:
        db = await self._conn()
        return await db.fetchone(sql, params)

    async def _fetchall(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[Any]:
        db = await self._conn()
        return await db.fetchall(sql, params)

    async def _fetchval(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> Any:
        db = await self._conn()
        return await db.fetchval(sql, params)

    async def _commit(self) -> None:
        db = await self._conn()
        await db.commit()

    async def _execute_many(self, sql: str, params_list: list[list[Any] | tuple[Any, ...]]) -> None:
        db = await self._conn()
        await db.executemany(sql, params_list)
