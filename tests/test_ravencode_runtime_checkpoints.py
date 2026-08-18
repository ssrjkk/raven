from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import ravencode.runtime.checkpoints as ckpt_mod
from ravencode.runtime.checkpoints import (
    CheckpointManager,
    checkpoint_list,
    checkpoint_restore,
    checkpoint_save,
    get_checkpoint_manager,
)


@pytest.fixture(autouse=True)
def reset() -> Generator[None, None, None]:
    ckpt_mod._checkpoint_manager = None
    yield
    ckpt_mod._checkpoint_manager = None


def _manager(tmp_path) -> CheckpointManager:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "a.txt").write_text("hello", encoding="utf-8")
    return CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "data" / "checkpoints"))


class TestInit:
    def test_resolves_paths(self, tmp_path) -> None:
        mgr = CheckpointManager(workspace=str(tmp_path / "ws"), storage_dir=str(tmp_path / "cp"))
        assert mgr._workspace == (tmp_path / "ws").resolve()
        assert mgr._storage == (tmp_path / "cp").resolve()

    def test_defaults(self) -> None:
        mgr = CheckpointManager()
        assert mgr._workspace.name == "workspace"


class TestSave:
    async def test_save_creates_files(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        result = await mgr.save(description="first")
        assert result.startswith("[ok] checkpoint 'cp_")
        assert result.endswith("saved (1 files)")
        cid = result.split("'")[1]
        cp_dir = tmp_path / "data" / "checkpoints" / cid
        assert (cp_dir / "snapshot.json").is_file()
        assert (cp_dir / "info.json").is_file()
        info = json.loads((cp_dir / "info.json").read_text(encoding="utf-8"))
        assert info["description"] == "first"
        assert info["files"] == 1
        assert (tmp_path / "data" / "checkpoints" / "index.json").is_file()

    async def test_save_skips_unreadable(self, tmp_path, monkeypatch) -> None:
        mgr = _manager(tmp_path)

        def broken_read(self, **kw):
            raise OSError("denied")

        monkeypatch.setattr(Path, "read_text", broken_read)
        result = await mgr.save()
        assert result.endswith("saved (0 files)")


class TestRestore:
    async def test_restore_not_found(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        assert await mgr.restore("cp_missing") == "[error] checkpoint not found: cp_missing"

    async def test_restore_missing_snapshot(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        (tmp_path / "data" / "checkpoints" / "cp_x").mkdir(parents=True)
        assert await mgr.restore("cp_x") == "[error] snapshot data missing for: cp_x"

    async def test_restore_corrupt_snapshot(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        cp = tmp_path / "data" / "checkpoints" / "cp_x"
        cp.mkdir(parents=True)
        (cp / "snapshot.json").write_text("not json", encoding="utf-8")
        result = await mgr.restore("cp_x")
        assert "cannot read snapshot" in result

    async def test_restore_writes_files(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        cid = (await mgr.save()).split("'")[1]
        (tmp_path / "workspace" / "a.txt").write_text("gone", encoding="utf-8")
        result = await mgr.restore(cid)
        assert result == f"[ok] checkpoint '{cid}' restored (1 files)"
        assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "hello"

    async def test_restore_nested_paths(self, tmp_path) -> None:
        ws = tmp_path / "workspace"
        (ws / "sub" / "dir").mkdir(parents=True)
        (ws / "sub" / "dir" / "n.txt").write_text("nested", encoding="utf-8")
        mgr = CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "cp"))
        cid = (await mgr.save()).split("'")[1]
        (ws / "sub" / "dir" / "n.txt").unlink()
        await mgr.restore(cid)
        assert (ws / "sub" / "dir" / "n.txt").read_text(encoding="utf-8") == "nested"


class TestDelete:
    async def test_delete_not_found(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        assert await mgr.delete("cp_missing") == "[error] checkpoint not found: cp_missing"

    async def test_delete_removes_dir(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        cid = (await mgr.save()).split("'")[1]
        result = await mgr.delete(cid)
        assert result == f"[ok] checkpoint '{cid}' deleted"
        assert not (tmp_path / "data" / "checkpoints" / cid).exists()


class TestIndex:
    async def test_list(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        await mgr.save(description="d")
        items = mgr.list()
        assert len(items) == 1
        assert items[0]["description"] == "d"
        assert items[0]["id"].startswith("cp_")

    async def test_list_empty(self, tmp_path) -> None:
        mgr = CheckpointManager(workspace=str(tmp_path), storage_dir=str(tmp_path / "cp"))
        assert mgr.list() == []

    def test_load_index_corrupt(self, tmp_path) -> None:
        mgr = CheckpointManager(workspace=str(tmp_path), storage_dir=str(tmp_path / "cp"))
        idx_dir = tmp_path / "cp"
        idx_dir.mkdir()
        (idx_dir / "index.json").write_text("garbage", encoding="utf-8")
        mgr._load_index()
        assert mgr._checkpoints == {}


class TestGlobals:
    def test_get_manager_singleton(self) -> None:
        assert get_checkpoint_manager() is get_checkpoint_manager()

    async def test_checkpoint_save_delegates(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="[ok] checkpoint 'cp' saved (0 files)")
        monkeypatch.setattr(
            ckpt_mod, "get_checkpoint_manager", lambda: type("M", (), {"save": fake})()
        )
        assert await checkpoint_save() == "[ok] checkpoint 'cp' saved (0 files)"

    async def test_checkpoint_restore_delegates(self, monkeypatch) -> None:
        fake = AsyncMock(return_value="[ok] restored")
        monkeypatch.setattr(ckpt_mod, "get_checkpoint_manager", lambda: type("M", (), {"restore": fake})())
        assert await checkpoint_restore("cp") == "[ok] restored"

    async def test_checkpoint_list_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(ckpt_mod, "get_checkpoint_manager", lambda: CheckpointManager(workspace=str(tmp_path), storage_dir=str(tmp_path / "cp")))
        assert await checkpoint_list() == "(no checkpoints)"

    async def test_checkpoint_list_renders(self, tmp_path) -> None:
        mgr = _manager(tmp_path)
        await mgr.save(description="hello cp")
        ckpt_mod._checkpoint_manager = mgr
        text = await checkpoint_list()
        assert "hello cp" in text
