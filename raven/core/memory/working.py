from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

from raven.core.memory.base import MemoryEntry, MemoryTier


class WorkingMemory:
    """In-process ephemeral memory with TTL and LRU eviction."""

    def __init__(self, max_entries: int = 200, default_ttl: float = 300.0):
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._entries: OrderedDict[str, tuple[str, dict[str, Any], float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        expires = time.monotonic() + self._default_ttl
        async with self._lock:
            self._entries[key] = (value, metadata or {}, expires)
            self._entries.move_to_end(key)
            self._evict()

    async def recall(self, key: str) -> str | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            val, _, expires = entry
            if time.monotonic() > expires:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return val

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._entries.pop(key, None) is not None

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        q = query.lower()
        async with self._lock:
            now = time.monotonic()
            for k, (v, m, exp) in self._entries.items():
                if now > exp:
                    continue
                if q in k.lower() or q in v.lower():
                    results.append(
                        MemoryEntry(key=k, value=v, tier=MemoryTier.WORKING, metadata=m)
                    )
            return results[:limit]

    async def list_keys(self) -> list[str]:
        async with self._lock:
            now = time.monotonic()
            return [k for k, (_, _, exp) in self._entries.items() if now <= exp]

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    async def cleanup_expired(self) -> int:
        now = time.monotonic()
        async with self._lock:
            stale = [k for k, (_, _, exp) in self._entries.items() if now > exp]
            for k in stale:
                del self._entries[k]
            return len(stale)

    def _evict(self) -> None:
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
