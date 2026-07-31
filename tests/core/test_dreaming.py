from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from raven.core.memory.manager import MemoryManager


@pytest.fixture
def memory(tmp_path: Path) -> MemoryManager:
    return MemoryManager(workspace=tmp_path)


class TestConsolidation:
    @pytest.mark.asyncio
    async def test_consolidate_empty(self, memory: MemoryManager):
        from raven.core.dreaming.consolidation import consolidate_memories

        stats = await consolidate_memories(memory)
        assert "working_expired" in stats
        assert "promoted_to_session" in stats
        assert "promoted_to_long_term" in stats

    @pytest.mark.asyncio
    async def test_consolidate_promotes_working(self, memory: MemoryManager):
        from raven.core.dreaming.consolidation import consolidate_memories

        await memory.working.store("test:key", "test value")
        stats = await consolidate_memories(memory)
        assert stats["promoted_to_session"] >= 1
        assert await memory.working.recall("test:key") is None

    @pytest.mark.asyncio
    async def test_extract_topics(self, memory: MemoryManager):
        from raven.core.dreaming.consolidation import extract_topics_from_lt

        await memory.long_term.store("user:alice", "Alice prefers Python")
        await memory.long_term.store("user:bob", "Bob uses TypeScript")
        topics = await extract_topics_from_lt(memory)
        assert "user" in topics


class TestPatterns:
    @pytest.mark.asyncio
    async def test_detect_no_patterns(self, memory: MemoryManager):
        from raven.core.dreaming.patterns import detect_patterns

        patterns = await detect_patterns(memory)
        assert patterns == []

    @pytest.mark.asyncio
    async def test_detect_recurring_prefix(self, memory: MemoryManager):
        from raven.core.dreaming.patterns import detect_patterns

        await memory.long_term.store("bug:login", "Login page crashes on empty input")
        await memory.long_term.store("bug:signup", "Signup fails on special chars")
        patterns = await detect_patterns(memory, min_frequency=1)
        assert any(p["type"] == "recurring_topic" for p in patterns)


class TestGeneration:
    @pytest.mark.asyncio
    async def test_generate_empty_patterns(self, memory: MemoryManager):
        from raven.core.dreaming.generation import generate_skills

        skills = await generate_skills(memory, [])
        assert skills == []

    @pytest.mark.asyncio
    async def test_generate_from_topic_pattern(self, memory: MemoryManager):
        from raven.core.dreaming.generation import generate_skills

        patterns: list[dict[str, str | int]] = [{"type": "recurring_topic", "pattern": "bug", "frequency": 3}]
        skills = await generate_skills(memory, patterns)
        assert len(skills) >= 1
        assert "bug" in skills[0]["name"]

    @pytest.mark.asyncio
    async def test_generate_from_phrase_pattern(self, memory: MemoryManager):
        from raven.core.dreaming.generation import generate_skills

        patterns: list[dict[str, str | int]] = [{"type": "recurring_phrase", "pattern": "login fails", "frequency": 2}]
        skills = await generate_skills(memory, patterns)
        assert len(skills) >= 1

    def test_pattern_to_skill_topic(self):
        from raven.core.dreaming.generation import _pattern_to_skill

        skill = _pattern_to_skill("recurring_topic", "bug_fix")
        assert skill is not None
        assert "bug" in skill["name"]

    def test_pattern_to_skill_phrase(self):
        from raven.core.dreaming.generation import _pattern_to_skill

        skill = _pattern_to_skill("recurring_phrase", "memory leak")
        assert skill is not None
        assert "memory" in skill["name"]

    def test_pattern_to_skill_unknown_type(self):
        from raven.core.dreaming.generation import _pattern_to_skill

        assert _pattern_to_skill("unknown", "test") is None


class TestEngine:
    @pytest.mark.asyncio
    async def test_engine_disabled_by_flag(self, monkeypatch: pytest.MonkeyPatch):
        from raven.core.dreaming.engine import DreamEngine
        from raven.core.features import FeatureFlags

        flags = FeatureFlags()
        flags.dreaming = False
        monkeypatch.setattr("raven.core.dreaming.engine.FeatureFlags.get", lambda: flags)

        engine = DreamEngine(memory=AsyncMock())
        await engine.start()
        assert not engine.is_running

    @pytest.mark.asyncio
    async def test_cycle_once_returns_stats(self, memory: MemoryManager):
        from raven.core.dreaming.engine import DreamEngine

        engine = DreamEngine(memory=memory, idle_timeout=0, cycle_interval=999)
        stats = await engine.cycle_once()
        assert "consolidation" in stats
        assert "patterns_detected" in stats
        assert "skills_proposed" in stats

    @pytest.mark.asyncio
    async def test_cycle_with_memories(self, memory: MemoryManager):
        from raven.core.dreaming.engine import DreamEngine

        await memory.long_term.store("user:alice", "Alice likes Python")
        await memory.long_term.store("user:bob", "Bob likes Python too")

        engine = DreamEngine(memory=memory, idle_timeout=0, cycle_interval=999)
        stats = await engine.cycle_once()
        assert stats["patterns_detected"] >= 0

    @pytest.mark.asyncio
    async def test_engine_start_stop(self, memory: MemoryManager, monkeypatch: pytest.MonkeyPatch):
        from raven.core.dreaming.engine import DreamEngine
        from raven.core.features import FeatureFlags

        flags = FeatureFlags()
        flags.dreaming = True
        monkeypatch.setattr("raven.core.dreaming.engine.FeatureFlags.get", lambda: flags)

        engine = DreamEngine(memory=memory, idle_timeout=0, cycle_interval=999)
        await engine.start()
        assert engine.is_running
        await engine.stop()
        assert not engine.is_running

    def test_get_engine_no_args_raises(self, monkeypatch: pytest.MonkeyPatch):
        import raven.core.dreaming.engine as dreng

        monkeypatch.setattr(dreng, "_engine_instance", None)
        from raven.core.dreaming.engine import get_dream_engine

        with pytest.raises(RuntimeError):
            get_dream_engine()

    def test_get_engine_instance_with_args(self, monkeypatch: pytest.MonkeyPatch):
        import raven.core.dreaming.engine as dreng

        monkeypatch.setattr(dreng, "_engine_instance", None)
        from raven.core.dreaming.engine import get_dream_engine

        engine = get_dream_engine(memory=AsyncMock())
        assert engine is not None
        assert get_dream_engine() is engine
