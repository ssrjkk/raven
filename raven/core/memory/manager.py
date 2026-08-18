from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.memory.base import MemoryEntry, MemoryTier
from raven.core.memory.knowledge import KnowledgeBase
from raven.core.memory.long_term import LongTermMemory
from raven.core.memory.session import SessionMemory
from raven.core.memory.working import WorkingMemory

if TYPE_CHECKING:
    from raven.core.db import Database


class MemoryManager:
    """Unified facade over all four memory tiers."""

    def __init__(self, db: Database | None = None, workspace: Path | None = None):
        self.working = WorkingMemory()
        self.session = SessionMemory(db)
        self.long_term = LongTermMemory(workspace)
        self.knowledge = KnowledgeBase(workspace)
        self._tiers: dict[MemoryTier, WorkingMemory | SessionMemory | LongTermMemory | KnowledgeBase] = {
            MemoryTier.WORKING: self.working,
            MemoryTier.SESSION: self.session,
            MemoryTier.LONG_TERM: self.long_term,
            MemoryTier.KNOWLEDGE: self.knowledge,
        }

    async def store(
        self,
        key: str,
        value: str,
        tier: MemoryTier = MemoryTier.WORKING,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        store = self._tiers.get(tier)
        if store:
            await store.store(key, value, metadata)
            logger.debug("[memory] stored {} in {}", key, tier.value)

    async def recall(self, key: str, tier: MemoryTier = MemoryTier.WORKING) -> str | None:
        store = self._tiers.get(tier)
        if store:
            return await store.recall(key)
        return None

    async def delete(self, key: str, tier: MemoryTier = MemoryTier.WORKING) -> bool:
        store = self._tiers.get(tier)
        if store:
            return await store.delete(key)
        return False

    async def search(
        self,
        query: str,
        tiers: list[MemoryTier] | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        targets = tiers or list(MemoryTier)
        results: list[MemoryEntry] = []
        for t in targets:
            store = self._tiers.get(t)
            if store:
                try:
                    hits = await store.search(query, limit=limit)
                    results.extend(hits)
                except Exception:
                    logger.opt(exception=True).warning("[memory] search failed in {}", t.value)
        results.sort(key=lambda e: e.score, reverse=True)
        return results[:limit]

    async def store_many(
        self,
        entries: list[tuple[str, str, MemoryTier, dict[str, Any] | None]],
    ) -> None:
        for key, value, tier, metadata in entries:
            await self.store(key, value, tier, metadata)

    async def promote(self, key: str, from_tier: MemoryTier, to_tier: MemoryTier) -> bool:
        value = await self.recall(key, from_tier)
        if value is None:
            return False
        await self.store(key, value, to_tier)
        return True

    async def consolidate(self) -> dict[str, int]:
        return {"working_expired": await self.working.cleanup_expired()}

    async def status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tier in MemoryTier:
            store = self._tiers.get(tier)
            if not store:
                counts[tier.value] = 0
                continue
            try:
                counts[tier.value] = len(await store.list_keys())
            except Exception:
                logger.opt(exception=True).warning("[memory] status failed for {}", tier.value)
                counts[tier.value] = -1
        return counts
