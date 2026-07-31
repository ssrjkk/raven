from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from raven.core.memory.base import MemoryEntry, MemoryTier

if TYPE_CHECKING:
    from raven.core.db import Database


_ROLE_MAP: dict[str, str] = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "tool": "tool",
}


class SessionMemory:
    """Per-session conversation history backed by the message store."""

    def __init__(self, db: Database | None = None):
        self._db = db

    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        session_id = meta.get("session_id", "default")
        role_raw = meta.get("role", "system")
        role_val = _ROLE_MAP.get(role_raw, "system")
        if self._db:
            try:
                from raven.core.models import Message

                msg = Message(
                    session_id=session_id,
                    role=cast("Any", role_val),
                    content=value,
                    metadata={"memory_key": key, **meta},
                )
                await self._db.save_message(msg)
            except Exception:
                logger.opt(exception=True).warning("[session] store failed")

    async def recall(self, key: str) -> str | None:
        if not self._db:
            return None
        try:
            msgs = await self._db.get_session_messages("default", limit=50)
            for m in reversed(msgs):
                meta = getattr(m, "metadata", {}) or {}
                if isinstance(meta, dict) and meta.get("memory_key") == key:
                    return m.content
            return None
        except Exception:
            logger.opt(exception=True).warning("[session] recall failed")
            return None

    async def delete(self, key: str) -> bool:
        return False

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        if not self._db:
            return []
        results: list[MemoryEntry] = []
        q = query.lower()
        try:
            msgs = await self._db.get_session_messages("default", limit=100)
            for m in msgs:
                if q in m.content.lower():
                    results.append(
                        MemoryEntry(
                            key=f"msg-{m.id}",
                            value=m.content,
                            tier=MemoryTier.SESSION,
                            metadata={"role": m.role, "session_id": "default"},
                        )
                    )
            return results[:limit]
        except Exception:
            logger.opt(exception=True).warning("[session] search failed")
            return []

    async def list_keys(self) -> list[str]:
        return []

    async def clear(self) -> None:
        pass
