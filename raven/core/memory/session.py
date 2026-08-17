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
        self._keys: dict[str, str] = {}

    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        session_id = meta.get("session_id", "default")
        role_raw = meta.get("role", "system")
        role_val = _ROLE_MAP.get(role_raw, "system")
        self._keys[key] = session_id
        if self._db:
            try:
                from raven.core.models import Message

                await self._db.get_or_create_session(session_id, channel="memory", user_id="system")
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
            session_id = self._keys.get(key, "default")
            msgs = await self._db.get_session_messages(session_id, limit=5000)
            for m in reversed(msgs):
                meta = getattr(m, "metadata", {}) or {}
                if isinstance(meta, dict) and meta.get("memory_key") == key:
                    return m.content
            return None
        except Exception:
            logger.opt(exception=True).warning("[session] recall failed")
            return None

    async def delete(self, key: str) -> bool:
        if not self._db:
            self._keys.pop(key, None)
            return False
        session_id = self._keys.pop(key, "default")
        try:
            msgs = await self._db.get_session_messages(session_id, limit=5000)
            kept = [m for m in msgs if (m.metadata or {}).get("memory_key") != key]
            if len(kept) == len(msgs):
                return False
            await self._db.replace_session_messages(session_id, [dict(m.__dict__) for m in kept])
            return True
        except Exception:
            logger.opt(exception=True).warning("[session] delete failed")
            return False

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        if not self._db:
            return []
        results: list[MemoryEntry] = []
        q = query.lower()
        try:
            for session_id in set(self._keys.values()) | {"default"}:
                msgs = await self._db.get_session_messages(session_id, limit=5000)
                for m in msgs:
                    if q in m.content.lower():
                        results.append(
                            MemoryEntry(
                                key=f"msg-{m.id}",
                                value=m.content,
                                tier=MemoryTier.SESSION,
                                metadata={"role": m.role, "session_id": session_id},
                            )
                        )
            return results[:limit]
        except Exception:
            logger.opt(exception=True).warning("[session] search failed")
            return []

    async def list_keys(self) -> list[str]:
        return list(self._keys)

    async def clear(self) -> None:
        for key in list(self._keys):
            await self.delete(key)
