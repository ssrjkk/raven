from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Any


class SharedMemory:
    def __init__(self, max_facts: int = 100) -> None:
        self._max_facts = max_facts
        self._facts: OrderedDict[str, Any] = OrderedDict()
        self._lock = Lock()

    def store(self, key: str, value: object) -> None:
        with self._lock:
            self._facts[key] = value
            self._facts.move_to_end(key)
            self._evict_oldest()

    def get(self, key: str, default: object = None) -> object:
        with self._lock:
            return self._facts.get(key, default)

    def remove(self, key: str) -> None:
        with self._lock:
            self._facts.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._facts.clear()

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._facts.keys())

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._facts)

    def search(self, predicate: Callable[[str, Any], bool]) -> dict[str, Any]:
        with self._lock:
            return {k: v for k, v in self._facts.items() if predicate(k, v)}

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._facts)

    def _evict_oldest(self) -> None:
        while len(self._facts) > self._max_facts:
            self._facts.popitem(last=False)
