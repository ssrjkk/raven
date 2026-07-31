from __future__ import annotations

import asyncio

import pytest

from raven.core.memory import (
    KnowledgeBase,
    LongTermMemory,
    MemoryManager,
    MemoryTier,
    WorkingMemory,
)


class TestWorkingMemory:
    async def test_store_and_recall(self):
        wm = WorkingMemory(default_ttl=60)
        await wm.store("key1", "value1")
        assert await wm.recall("key1") == "value1"

    async def test_recall_missing(self):
        wm = WorkingMemory()
        assert await wm.recall("nonexistent") is None

    async def test_ttl_expiry(self):
        wm = WorkingMemory(default_ttl=0.05)
        await wm.store("key1", "value1")
        assert await wm.recall("key1") == "value1"
        await asyncio.sleep(0.06)
        assert await wm.recall("key1") is None

    async def test_delete(self):
        wm = WorkingMemory()
        await wm.store("key1", "value1")
        assert await wm.delete("key1") is True
        assert await wm.recall("key1") is None

    async def test_search(self):
        wm = WorkingMemory()
        await wm.store("alpha", "hello world")
        await wm.store("beta", "goodbye world")
        results = await wm.search("hello")
        assert len(results) == 1
        assert results[0].key == "alpha"

    async def test_clear(self):
        wm = WorkingMemory()
        await wm.store("key1", "val1")
        await wm.clear()
        assert await wm.list_keys() == []

    async def test_eviction(self):
        wm = WorkingMemory(max_entries=2)
        await wm.store("a", "1")
        await wm.store("b", "2")
        await wm.store("c", "3")
        keys = await wm.list_keys()
        assert len(keys) == 2
        assert "a" not in keys


class TestLongTermMemory:
    async def test_store_and_recall(self, tmp_path):
        ltm = LongTermMemory(tmp_path)
        await ltm.store("user:name", "Alice")
        assert await ltm.recall("user:name") == "Alice"

    async def test_recall_missing(self, tmp_path):
        ltm = LongTermMemory(tmp_path)
        assert await ltm.recall("nonexistent") is None

    async def test_delete(self, tmp_path):
        ltm = LongTermMemory(tmp_path)
        await ltm.store("user:name", "Alice")
        assert await ltm.delete("user:name") is True
        assert await ltm.recall("user:name") is None

    async def test_search(self, tmp_path):
        ltm = LongTermMemory(tmp_path)
        await ltm.store("user:name", "Alice")
        await ltm.store("project:name", "Raven")
        results = await ltm.search("Raven")
        assert len(results) == 1

    async def test_category_routing(self, tmp_path):
        ltm = LongTermMemory(tmp_path)
        await ltm.store("user:email", "a@b.com")
        await ltm.store("project:repo", "github")
        await ltm.store("lessons:learned", "use types")
        assert await ltm.recall("user:email") == "a@b.com"


class TestKnowledgeBase:
    async def test_store_and_recall(self, tmp_path):
        kb = KnowledgeBase(tmp_path)
        await kb.store("python", "A programming language")
        val = await kb.recall("python")
        assert val is not None
        assert "programming" in val

    async def test_delete(self, tmp_path):
        kb = KnowledgeBase(tmp_path)
        await kb.store("python", "lang")
        assert await kb.delete("python") is True
        assert await kb.recall("python") is None

    async def test_search(self, tmp_path):
        kb = KnowledgeBase(tmp_path)
        await kb.store("python", "A programming language")
        await kb.store("snake", "An animal")
        results = await kb.search("programming")
        assert len(results) >= 1

    async def test_add_relation(self, tmp_path):
        kb = KnowledgeBase(tmp_path)
        await kb.store("docker", "containers")
        await kb.store("compose", "multi-container")
        await kb.add_relation("docker", "compose", "related")
        related = await kb.get_related("docker")
        assert len(related) == 1
        assert related[0]["target_id"] == "compose"


class TestMemoryManager:
    async def test_store_and_recall_working(self):
        mm = MemoryManager()
        await mm.store("k1", "v1", MemoryTier.WORKING)
        val = await mm.recall("k1", MemoryTier.WORKING)
        assert val == "v1"

    async def test_promote(self):
        mm = MemoryManager()
        await mm.store("k1", "v1", MemoryTier.WORKING)
        ok = await mm.promote("k1", MemoryTier.WORKING, MemoryTier.LONG_TERM)
        assert ok is True

    async def test_search_all_tiers(self):
        mm = MemoryManager()
        await mm.store("greeting", "hello world", MemoryTier.WORKING)
        results = await mm.search("hello")
        assert len(results) >= 1

    async def test_status(self):
        mm = MemoryManager()
        status = await mm.status()
        assert "working" in status
        assert "long_term" in status
