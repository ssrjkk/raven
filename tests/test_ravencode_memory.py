from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ravencode.runtime.context import MemoryStore
from ravencode.runtime.tools import execute_tool, set_agent_memory_store


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(path=str(tmp_path / "mem.json"))


class TestMemoryPush:
    async def test_push_appends_new_item(self, store: MemoryStore):
        assert await store.push("notes", "fixed the parser bug") is True
        assert await store.get("notes") == ["fixed the parser bug"]

    async def test_push_dedupes_case_and_whitespace(self, store: MemoryStore):
        await store.push("notes", "Fixed the parser bug")
        assert await store.push("notes", "  fixed   the parser BUG  ") is False
        assert await store.get("notes") == ["Fixed the parser bug"]

    async def test_push_caps_list(self, store: MemoryStore):
        for i in range(30):
            await store.push("notes", f"fact {i}", max_items=20)
        notes = await store.get("notes")
        assert len(notes) == 20
        assert notes[-1] == "fact 29"

    async def test_push_rejects_empty(self, store: MemoryStore):
        assert await store.push("notes", "   ") is False

    async def test_push_converts_non_list_key(self, store: MemoryStore):
        await store.set("notes", "plain string")
        assert await store.push("notes", "new fact") is True
        assert await store.get("notes") == ["plain string", "new fact"]


class TestCompactLists:
    async def test_compact_removes_duplicates_and_caps(self, store: MemoryStore):
        await store.set(
            "notes",
            ["a", "A", "  a  ", "b"] + [f"x{i}" for i in range(25)],
        )
        removed = await store.compact_lists(max_items=10)
        notes = await store.get("notes")
        assert removed > 0
        assert len(notes) == 10
        lowered = [n.lower() for n in notes]
        assert len(lowered) == len(set(lowered))

    async def test_compact_ignores_non_lists(self, store: MemoryStore):
        await store.set("scalar", "keep me")
        removed = await store.compact_lists()
        assert await store.get("scalar") == "keep me"
        assert removed == 0


class TestMemoryTools:
    async def test_remember_and_recall_roundtrip(self, store: MemoryStore):
        set_agent_memory_store(store)
        out = await execute_tool("memory_remember", {"fact": "user prefers tabs"})
        assert out == "remembered"
        out = await execute_tool("memory_recall", {})
        assert "user prefers tabs" in out

    async def test_remember_duplicate_reported(self, store: MemoryStore):
        set_agent_memory_store(store)
        await execute_tool("memory_remember", {"fact": "uses sqlite"})
        out = await execute_tool("memory_remember", {"fact": "Uses SQLITE"})
        assert out == "duplicate ignored (already known)"

    async def test_recall_empty_key(self, store: MemoryStore):
        set_agent_memory_store(store)
        out = await execute_tool("memory_recall", {"key": "nothing"})
        assert "nothing remembered" in out

    async def test_no_store_configured(self):
        set_agent_memory_store(None)
        out = await execute_tool("memory_remember", {"fact": "x"})
        assert out.startswith("[error]")

    async def test_validation_error_on_empty_fact(self, store: MemoryStore):
        set_agent_memory_store(store)
        out = await execute_tool("memory_remember", {"fact": "   "})
        assert out.startswith("[validation_error]")

    async def test_definitions_include_memory_tools(self):
        from ravencode.runtime.tools import get_tool_definitions

        names = {d["function"]["name"] for d in get_tool_definitions()}
        assert "memory_remember" in names
        assert "memory_recall" in names


class TestAgentWiring:
    async def test_agent_exposes_store_to_tools(self, tmp_path: Path):
        from ravencode.runtime.agent_core import AgentConfig, ReActAgent

        mem_path = str(tmp_path / "agent_mem.json")
        ReActAgent(config=AgentConfig(memory_path=mem_path, proactive_scan=False))
        out = await execute_tool("memory_remember", {"fact": "wired correctly", "key": "notes"})
        assert out == "remembered"
        store = MemoryStore(path=mem_path)
        assert await store.get("notes") == ["wired correctly"]
