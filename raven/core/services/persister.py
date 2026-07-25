from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass
class PersisterResult:
    id: str
    ok: bool
    error: str | None = None


class PersisterBackend(ABC):
    @abstractmethod
    async def insert(self, collection: str, data: dict[str, Any]) -> str: ...

    @abstractmethod
    async def get(self, collection: str, id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def search(self, collection: str, query: str, limit: int = 10) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def delete(self, collection: str, id: str) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...


class SQLitePersister(PersisterBackend):
    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def _ensure(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(str(self._path))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    collection TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            await self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_entities_collection ON entities(collection)
            """)
            await self._conn.commit()
        return self._conn

    async def insert(self, collection: str, data: dict[str, Any]) -> str:
        conn = await self._ensure()
        id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO entities (id, collection, data) VALUES (?, ?, ?)",
            (id, collection, json.dumps(data, default=str)),
        )
        await conn.commit()
        return id

    async def get(self, collection: str, id: str) -> dict[str, Any] | None:
        conn = await self._ensure()
        cursor = await conn.execute(
            "SELECT data FROM entities WHERE id = ? AND collection = ?",
            (id, collection),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        data: dict[str, Any] = json.loads(row["data"])
        return data

    async def search(self, collection: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        conn = await self._ensure()
        cursor = await conn.execute(
            "SELECT id, data FROM entities WHERE collection = ? AND data LIKE ? LIMIT ?",
            (collection, f"%{query}%", limit),
        )
        rows = await cursor.fetchall()
        return [{"id": r["id"], **json.loads(r["data"])} for r in rows]

    async def delete(self, collection: str, id: str) -> bool:
        conn = await self._ensure()
        cursor = await conn.execute(
            "DELETE FROM entities WHERE id = ? AND collection = ?",
            (id, collection),
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None


_backend: PersisterBackend | None = None


def get_persister(db_path: str | Path = "data/services.db") -> PersisterBackend:
    global _backend
    if _backend is None:
        _backend = SQLitePersister(db_path)
    return _backend
