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
