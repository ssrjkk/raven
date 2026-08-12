from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raven.core.asyncdb import AsyncDB, connect_backend


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
        self._path = str(db_path)
        self._db: AsyncDB | None = None

    async def _ensure(self) -> AsyncDB:
        if self._db is None:
            self._db = connect_backend(self._path)
            await self._db.connect()
            if self._db.dialect == "postgresql":
                await self._db.execute("""
                    CREATE TABLE IF NOT EXISTS entities (
                        id TEXT PRIMARY KEY,
                        collection TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())
                    )
                """)
            else:
                await self._db.execute("""
                    CREATE TABLE IF NOT EXISTS entities (
                        id TEXT PRIMARY KEY,
                        collection TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
            await self._db.execute("""
                CREATE INDEX IF NOT EXISTS idx_entities_collection ON entities(collection)
            """)
            await self._db.commit()
        return self._db

    async def insert(self, collection: str, data: dict[str, Any]) -> str:
        db = await self._ensure()
        id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO entities (id, collection, data) VALUES (?, ?, ?)",
            (id, collection, json.dumps(data, default=str)),
        )
        await db.commit()
        return id

    async def get(self, collection: str, id: str) -> dict[str, Any] | None:
        db = await self._ensure()
        row = await db.fetchone(
            "SELECT data FROM entities WHERE id = ? AND collection = ?",
            (id, collection),
        )
        if row is None:
            return None
        data: dict[str, Any] = json.loads(row["data"])
        return data

    async def search(self, collection: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        db = await self._ensure()
        rows = await db.fetchall(
            "SELECT id, data FROM entities WHERE collection = ? AND data LIKE ? LIMIT ?",
            (collection, f"%{query}%", limit),
        )
        return [{"id": r["id"], **json.loads(r["data"])} for r in rows]

    async def delete(self, collection: str, id: str) -> bool:
        db = await self._ensure()
        rowcount = await db.execute(
            "DELETE FROM entities WHERE id = ? AND collection = ?",
            (id, collection),
        )
        await db.commit()
        return rowcount is not None and rowcount > 0

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None


_backend: PersisterBackend | None = None


def get_persister(db_path: str | Path = "data/services.db") -> PersisterBackend:
    global _backend
    if _backend is None:
        _backend = SQLitePersister(db_path)
    return _backend
