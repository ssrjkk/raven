from __future__ import annotations

from pathlib import Path

import pytest

from raven.core.memory.base import MemoryTier
from raven.core.memory.manager import MemoryManager


@pytest.fixture
def memory(tmp_path: Path) -> MemoryManager:
    return MemoryManager(workspace=tmp_path)


class TestBackup:
    @pytest.mark.asyncio
    async def test_export_empty(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import export_memory

        dest = tmp_path / "backup.json"
        path = await export_memory(memory, dest=dest)
        assert path == dest
        assert dest.exists()
        assert dest.stat().st_size > 10

    @pytest.mark.asyncio
    async def test_export_with_data(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import export_memory

        await memory.store("wk:1", "working data", tier=MemoryTier.WORKING)
        await memory.store("lt:1", "long term data", tier=MemoryTier.LONG_TERM)
        dest = tmp_path / "backup2.json"
        await export_memory(memory, dest=dest)
        assert dest.exists()

    @pytest.mark.asyncio
    async def test_import_restores_data(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import export_memory, import_memory

        await memory.store("key1", "value1", tier=MemoryTier.WORKING)
        await memory.store("key2", "value2", tier=MemoryTier.LONG_TERM)
        dest = tmp_path / "backup3.json"
        await export_memory(memory, dest=dest)

        fresh = MemoryManager(workspace=tmp_path / "new_ws")
        counts = await import_memory(fresh, dest)
        assert sum(counts.values()) >= 2
        assert await fresh.recall("key1", tier=MemoryTier.WORKING) == "value1"
        assert await fresh.recall("key2", tier=MemoryTier.LONG_TERM) == "value2"

    @pytest.mark.asyncio
    async def test_import_nonexistent_file(self, memory: MemoryManager):
        from raven.core.backup import import_memory

        with pytest.raises(FileNotFoundError):
            await import_memory(memory, Path("/nonexistent/backup.json"))

    @pytest.mark.asyncio
    async def test_list_backups_empty(self, tmp_path: Path):
        from raven.core.backup import list_backups

        backups = await list_backups(backup_dir=tmp_path)
        assert backups == []

    @pytest.mark.asyncio
    async def test_list_backups_with_files(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import export_memory, list_backups

        for i in range(3):
            await export_memory(memory, dest=tmp_path / f"memory_backup_{i}.json")
        backups = await list_backups(backup_dir=tmp_path)
        assert len(backups) == 3
        assert all(b["filename"].startswith("memory_backup_") for b in backups)

    @pytest.mark.asyncio
    async def test_full_round_trip_all_tiers(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import export_memory, import_memory
        from raven.core.db import Database

        db = Database(tmp_path / "mem.db")
        await db.connect()
        mem = MemoryManager(db=db, workspace=tmp_path)
        await mem.store("w", "1", tier=MemoryTier.WORKING)
        await mem.store("s", "2", tier=MemoryTier.SESSION)
        await mem.store("l", "3", tier=MemoryTier.LONG_TERM)
        await mem.store("k", "4", tier=MemoryTier.KNOWLEDGE)
        dest = tmp_path / "rt.json"
        await export_memory(mem, dest=dest)

        fresh_db = Database(tmp_path / "fresh.db")
        await fresh_db.connect()
        fresh = MemoryManager(db=fresh_db, workspace=tmp_path / "fresh_ws")
        counts = await import_memory(fresh, dest)
        assert counts.get(MemoryTier.WORKING.value) == 1
        assert counts.get(MemoryTier.SESSION.value) == 1
        assert counts.get(MemoryTier.LONG_TERM.value) == 1
        assert counts.get(MemoryTier.KNOWLEDGE.value) == 1
        assert await fresh.recall("w", tier=MemoryTier.WORKING) == "1"
        assert await fresh.recall("s", tier=MemoryTier.SESSION) == "2"
        assert await fresh.recall("l", tier=MemoryTier.LONG_TERM) == "3"
        assert await fresh.recall("k", tier=MemoryTier.KNOWLEDGE) == "4"
        await db.disconnect()
        await fresh_db.disconnect()

    @pytest.mark.asyncio
    async def test_import_corrupt_json_raises_value_error(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import import_memory

        bad = tmp_path / "corrupt.json"
        bad.write_text("{not json at all", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            await import_memory(memory, bad)

    @pytest.mark.asyncio
    async def test_import_invalid_structure_raises(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import import_memory

        bad = tmp_path / "array.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(TypeError, match="invalid structure"):
            await import_memory(memory, bad)

    @pytest.mark.asyncio
    async def test_import_unknown_version_raises(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import import_memory

        old = tmp_path / "old.json"
        old.write_text('{"version": 0, "tiers": {}}', encoding="utf-8")
        with pytest.raises(ValueError, match="Unknown backup version"):
            await import_memory(memory, old)

    @pytest.mark.asyncio
    async def test_import_skips_unknown_tier(self, memory: MemoryManager, tmp_path: Path):
        from raven.core.backup import import_memory

        src = tmp_path / "mixed.json"
        src.write_text(
            '{"version": 1, "tiers": {"bogus_tier": [{"key": "a", "value": "b"}],'
            ' "working": [{"key": "ok", "value": "yes"}]}}',
            encoding="utf-8",
        )
        counts = await import_memory(memory, src)
        assert MemoryTier.WORKING.value in counts
        assert "bogus_tier" not in counts
        assert await memory.recall("ok", tier=MemoryTier.WORKING) == "yes"
