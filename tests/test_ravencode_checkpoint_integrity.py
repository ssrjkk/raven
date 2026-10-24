"""CheckpointManager integrity: unique ids, newest-first undo, index recovery, pruned snapshot walk."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

import ravencode.runtime.checkpoints as ckpt_mod
from ravencode.runtime.checkpoints import CheckpointManager
from ravencode.runtime.tools.wrappers import undo_changes_tool


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def reset_singleton() -> Generator[None, None, None]:
    ckpt_mod._checkpoint_manager = None
    yield
    ckpt_mod._checkpoint_manager = None


def _mgr(tmp_path: Path, files: dict[str, str] | None = None) -> CheckpointManager:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    for name, body in (files or {"a.txt": "hello"}).items():
        target = ws / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "cp"))


def _cid(result: str) -> str:
    return result.split("'")[1]


class TestUniqueIds:
    async def test_two_saves_in_the_same_second_keep_both_snapshots(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        first = _cid(await mgr.save("first"))
        (tmp_path / "workspace" / "a.txt").write_text("second state", encoding="utf-8")
        second = _cid(await mgr.save("second"))
        assert first != second, "same-second saves collided and overwrote the first checkpoint"
        assert [c["id"] for c in mgr.list()] == [first, second]

        await mgr.restore(first)
        assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "hello"
        await mgr.restore(second)
        assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "second state"

    async def test_ids_stay_within_the_safe_pattern(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        ids = [_cid(await mgr.save(f"n{i}")) for i in range(4)]
        assert len(set(ids)) == 4
        assert all(ckpt_mod._SAFE_CID.match(cid) for cid in ids)


class TestUndoTargetsTheNewest:
    """Ordering is decided by the recorded time, not by which line was appended last.

    The stamps are rewritten on disk instead of patching the clock: a global time.time patch is
    read by pytest's own duration accounting too, and it takes the run down with it.
    """

    @staticmethod
    def _restamp(storage: Path, cid: str, created: float) -> None:
        index_path = storage / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index[cid]["created"] = created
        _write_json(index_path, index)
        info_path = storage / cid / "info.json"
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info["created"] = created
        _write_json(info_path, info)

    async def test_list_is_ordered_by_recorded_time(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        (tmp_path / "workspace" / "newer.txt").write_text("NEWER", encoding="utf-8")
        later = _cid(await mgr.save("appended second"))
        older = _cid(await mgr.save("appended third"))
        storage = tmp_path / "cp"
        self._restamp(storage, older, 500.0)
        self._restamp(storage, later, 1_000.0)

        ordered = [c["id"] for c in mgr.list()]
        assert ordered == [older, later], f"insertion order leaked into list(): {ordered}"

    async def test_undo_restores_the_highest_created(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        target = tmp_path / "workspace" / "a.txt"
        target.write_text("first state", encoding="utf-8")
        newest = _cid(await mgr.save("newest content"))
        stale = _cid(await mgr.save("stale content"))
        storage = tmp_path / "cp"
        self._restamp(storage, stale, 500.0)
        self._restamp(storage, newest, 1_000.0)

        ckpt_mod._checkpoint_manager = mgr
        target.write_text("changed since", encoding="utf-8")

        result = await undo_changes_tool()
        assert result.startswith("[ok]"), result
        assert target.read_text(encoding="utf-8") == "first state"


class TestIndexRecovery:
    async def test_a_torn_index_is_rebuilt_from_the_snapshot_dirs(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        first = _cid(await mgr.save("one"))
        second = _cid(await mgr.save("two"))
        (tmp_path / "cp" / "index.json").write_text('{"cp_1": {"created": 1', encoding="utf-8")

        recovered = _mgr(tmp_path)
        assert sorted(c["id"] for c in recovered.list()) == sorted([first, second])
        # The restored manager can still delete and keeps the surviving entries.
        await recovered.delete(first)
        assert [c["id"] for c in recovered.list()] == [second]

    async def test_a_second_instance_does_not_clobber_the_first(self, tmp_path: Path) -> None:
        m1 = _mgr(tmp_path)
        a = _cid(await m1.save("by m1"))
        m2 = _mgr(tmp_path)  # started before m1 saved nothing, loads lazily
        b = _cid(await m2.save("by m2"))
        c = _cid(await m1.save("by m1 again"))
        assert sorted([a, b, c]) == sorted(c2["id"] for c2 in m1.list())
        assert sorted([a, b, c]) == sorted(c2["id"] for c2 in m2.list())

    async def test_index_lists_checkpoints_the_dir_scan_agrees_with(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        cid = _cid(await mgr.save("single"))
        index = json.loads((tmp_path / "cp" / "index.json").read_text(encoding="utf-8"))
        assert list(index) == [cid]
        assert (tmp_path / "cp" / cid / "info.json").is_file()


class TestSnapshotWalk:
    async def test_pruned_directories_are_not_snapshotted(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "src.py").write_text("print(1)", encoding="utf-8")
        for i in range(50):
            dep = ws / "node_modules" / "pkg"
            dep.mkdir(parents=True, exist_ok=True)
            (dep / f"dep{i}.js").write_text(f"export const v{i} = {i}", encoding="utf-8")
        mgr = CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "cp"))

        result = await mgr.save()
        assert result.endswith("saved (1 files)"), result
        snapshot = json.loads((tmp_path / "cp" / _cid(result) / "snapshot.json").read_text(encoding="utf-8"))
        assert list(snapshot) == ["src.py"]

    async def test_unreadable_files_are_reported_not_silently_dropped(self, tmp_path: Path) -> None:
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "a.txt").write_text("text", encoding="utf-8")
        (ws / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe binary")
        mgr = CheckpointManager(workspace=str(ws), storage_dir=str(tmp_path / "cp"))

        cid = _cid(await mgr.save())
        info = json.loads((tmp_path / "cp" / cid / "info.json").read_text(encoding="utf-8"))
        assert info["files"] == 1
        assert info["skipped"] == 1, "a file undo cannot revert went uncounted"

    async def test_a_failed_snapshot_write_leaves_the_previous_checkpoint_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = _mgr(tmp_path)
        cid = _cid(await mgr.save("keep"))
        snapshot_path = tmp_path / "cp" / cid / "snapshot.json"
        before = snapshot_path.read_text(encoding="utf-8")

        # This is the window a killed process used to catch mid-write. The helper must fail with
        # the original bytes untouched, not after truncating them. Path.replace is patched only for
        # the duration of the call: leaving it swapped into teardown breaks the reporting plugin.
        def failing_replace(self: Path, target: Any) -> None:
            raise OSError("disk full")

        with monkeypatch.context() as m:
            m.setattr(Path, "replace", failing_replace)
            with pytest.raises(OSError):
                ckpt_mod._write_atomic(snapshot_path, json.dumps({"a.txt": "half written"}))
            assert snapshot_path.read_text(encoding="utf-8") == before

        assert list((tmp_path / "cp" / cid).glob("*.tmp")) == []


class TestAtomicWrites:
    async def test_no_temp_files_survive_a_save_and_a_restore(self, tmp_path: Path) -> None:
        mgr = _mgr(tmp_path)
        cid = _cid(await mgr.save())
        (tmp_path / "workspace" / "b.txt").write_text("added", encoding="utf-8")
        await mgr.restore(cid)
        assert list((tmp_path / "cp").rglob("*.tmp")) == []
        assert list((tmp_path / "workspace").rglob("*.tmp")) == []

    async def test_a_failed_restore_does_not_truncate_the_live_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mgr = _mgr(tmp_path)
        cid = _cid(await mgr.save())
        target = tmp_path / "workspace" / "a.txt"
        target.write_text("work written after the checkpoint", encoding="utf-8")

        def failing_replace(self: Path, target: Any) -> None:
            raise OSError("volume locked")

        with monkeypatch.context() as m:
            m.setattr(Path, "replace", failing_replace)
            with pytest.raises(OSError):
                await mgr.restore(cid)
            assert target.read_text(encoding="utf-8") == "work written after the checkpoint"

        assert list((tmp_path / "workspace").rglob("*.tmp")) == []
        assert (await mgr.restore(cid)).startswith("[ok]")
        assert target.read_text(encoding="utf-8") == "hello"
