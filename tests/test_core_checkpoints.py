from __future__ import annotations

import json

import pytest


class TestCheckpoint:
    def setup_method(self) -> None:
        from raven.core.checkpoints import get_checkpoint_manager

        self.mgr = get_checkpoint_manager()

    def teardown_method(self) -> None:
        import shutil

        if hasattr(self.mgr, "_storage") and self.mgr._storage.exists():
            shutil.rmtree(self.mgr._storage, ignore_errors=True)

    def test_list_empty_initially(self) -> None:
        cps = self.mgr.list()
        assert cps == []

    @pytest.mark.asyncio
    async def test_save_creates_checkpoint(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "hello.txt").write_text("world")
        from raven.core.checkpoints import CheckpointManager

        mgr = CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "checkpoints"))
        result = await mgr.save(description="test save")
        assert "saved" in result
        assert len(mgr.list()) == 1

    @pytest.mark.asyncio
    async def test_restore_checkpoint(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "hello.txt").write_text("world")
        from raven.core.checkpoints import CheckpointManager

        mgr = CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "checkpoints"))
        result_cid = await mgr.save(description="test restore")
        cid_str = result_cid.split("'")[1]
        (ws / "hello.txt").write_text("modified")
        result = await mgr.restore(cid_str)
        assert "restored" in result
        assert (ws / "hello.txt").read_text() == "world"

    @pytest.mark.asyncio
    async def test_restore_nonexistent(self) -> None:
        result = await self.mgr.restore("nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "f.txt").write_text("data")
        from raven.core.checkpoints import CheckpointManager

        mgr = CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "checkpoints"))
        result_save = await mgr.save()
        cid_str = result_save.split("'")[1]
        result = await mgr.delete(cid_str)
        assert "deleted" in result
        assert len(mgr.list()) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self) -> None:
        result = await self.mgr.delete("nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_global_checkpoint_save_load(self) -> None:
        import raven.core.checkpoints as cp

        result = await cp.checkpoint_list()
        assert isinstance(result, str)
        assert "no checkpoints" in result or result == ""

    def test_load_index_corrupted(self, tmp_path: pytest.TempPathFactory) -> None:
        from raven.core.checkpoints import CheckpointManager

        storage = tmp_path / "checkpoints"
        storage.mkdir()
        (storage / "index.json").write_text("not valid json")
        mgr = CheckpointManager(workspace=str(tmp_path), storage_dir=str(storage))
        assert mgr.list() == []
