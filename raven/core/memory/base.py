from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class MemoryTier(StrEnum):
    WORKING = "working"
    SESSION = "session"
    LONG_TERM = "long_term"
    KNOWLEDGE = "knowledge"


@dataclass
class MemoryEntry:
    key: str
    value: str
    tier: MemoryTier
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0


class MemoryStore(Protocol):
    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None: ...

    async def recall(self, key: str) -> str | None: ...

    async def delete(self, key: str) -> bool: ...

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]: ...

    async def list_keys(self) -> list[str]: ...

    async def clear(self) -> None: ...
