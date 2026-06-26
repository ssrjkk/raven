from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any


class ResponseCache:
    def __init__(self, max_size: int = 256, ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def _key(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> str:
        raw = json.dumps({"messages": messages, "tools": tools}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> str | None:
        key = self._key(messages, tools)
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return str(value) if value is not None else None

    def set(self, messages: list[dict[str, Any]], value: str, tools: list[dict[str, Any]] | None = None) -> None:
        key = self._key(messages, tools)
        self._cache[key] = (time.time(), value)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


_cache: ResponseCache | None = None


def get_cache() -> ResponseCache:
    global _cache
    if _cache is None:
        _cache = ResponseCache()
    return _cache
