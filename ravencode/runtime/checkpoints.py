from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.config import data_path
from ravencode.runtime.fs_walk import iter_files

_SAFE_CID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_INDEX_NAME = "index.json"
_SNAPSHOT_NAME = "snapshot.json"
_INFO_NAME = "info.json"


def _write_atomic(path: Path, payload: str) -> None:
    """Replace *path* in one step.

    Truncate-then-write is what turned a killed process into a lost checkpoint set: the file was
    half-written, every reader failed to parse it, and the recovery was to start from nothing.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _ordered_items(checkpoints: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Oldest first, by the recorded timestamp rather than by insertion order.

    Lives at module scope because CheckpointManager.list shadows the builtin `list` inside the
    class body, and undo_changes takes the last entry - so this order decides which checkpoint
    a user gets back.
    """

    def key(item: tuple[str, dict[str, Any]]) -> tuple[float, str]:
        try:
            return (float(item[1].get("created", 0)), item[0])
        except (TypeError, ValueError):
            return (0.0, item[0])

    return sorted(checkpoints.items(), key=key)


class CheckpointManager:
    def __init__(self, workspace: str | None = None, storage_dir: str | Path | None = None) -> None:
        self._workspace = Path(workspace or "workspace").expanduser().resolve()
        self._storage = (Path(storage_dir) if storage_dir else data_path("checkpoints")).expanduser().resolve()
        self._checkpoints: dict[str, dict[str, Any]] = {}
        # _state_lock serialises the async entry points; _index_lock only guards the index file
        # itself, because it is taken inside asyncio.to_thread workers. Never hold one across the other.
        self._state_lock = asyncio.Lock()
        self._index_lock = threading.Lock()

    # -- index ----------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        self._load_index()
        return [
            {
                "id": cid,
                "created": data.get("created", 0),
                "description": data.get("description", ""),
                "files": data.get("files", 0),
                "skipped": data.get("skipped", 0),
            }
            for cid, data in _ordered_items(self._checkpoints)
        ]

    def _scan_dirs(self) -> dict[str, dict[str, Any]]:
        """Every checkpoint directory that carries an info.json, whether or not the index knows it."""
        found: dict[str, dict[str, Any]] = {}
        if not self._storage.is_dir():
            return found
        for child in sorted(self._storage.iterdir()):
            if not child.is_dir():
                continue
            info_file = child / _INFO_NAME
            if not info_file.is_file():
                continue
            try:
                info = _read_json(info_file)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Checkpoint {} has an unreadable info.json: {}", child.name, exc)
                continue
            if isinstance(info, dict):
                found[child.name] = info
        return found

    def _load_index(self) -> None:
        idx = self._storage / _INDEX_NAME
        data: dict[str, Any] = {}
        if idx.is_file():
            try:
                loaded = _read_json(idx)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Checkpoint index {} is unreadable ({}); rebuilding it from the snapshot dirs", idx, exc)
                loaded = None
            if isinstance(loaded, dict):
                data = {k: v for k, v in loaded.items() if isinstance(v, dict)}
            elif loaded is not None:
                logger.error("Checkpoint index {} holds {} not an object; rebuilding from the snapshot dirs",
                             idx, type(loaded).__name__)
        merged = self._scan_dirs()
        for cid, info in merged.items():
            data.setdefault(cid, info)
        self._checkpoints = data

    def _save_index(self) -> None:
        with self._index_lock:
            self._storage.mkdir(parents=True, exist_ok=True)
            _write_atomic(self._storage / _INDEX_NAME, json.dumps(self._checkpoints, ensure_ascii=False, indent=2))

    # -- workspace snapshot ----------------------------------------------------

    def _collect_snapshot(self) -> tuple[dict[str, str], int]:
        """Read the workspace once, off the event loop.

        The walk is pruned (node_modules, venvs, .git) because a snapshot of an installed
        frontend is hundreds of megabytes of text the restore path can never use, and binaries
        are counted rather than silently dropped.
        """
        snapshot: dict[str, str] = {}
        skipped = 0
        for path in iter_files(self._workspace):
            try:
                snapshot[str(path.relative_to(self._workspace))] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                skipped += 1
                logger.debug("Skipping file {}: {}", path, exc)
        return snapshot, skipped

    def _next_cid(self) -> str:
        """A unique id. Seconds alone collided, and the second save silently overwrote the first."""
        base = f"cp_{int(time.time())}"
        cid = base
        seq = 1
        while cid in self._checkpoints or (self._storage / cid).is_dir():
            cid = f"{base}-{seq}"
            seq += 1
        return cid

    async def save(self, description: str = "") -> str:
        snapshot, skipped = await asyncio.to_thread(self._collect_snapshot)
        async with self._state_lock:
            await asyncio.to_thread(self._load_index)
            cid = self._next_cid()
            info: dict[str, Any] = {
                "created": time.time(),
                "description": description,
                "files": len(snapshot),
                "skipped": skipped,
                "workspace": str(self._workspace),
            }
            cp_dir = self._storage / cid
            await asyncio.to_thread(cp_dir.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(_write_atomic, cp_dir / _SNAPSHOT_NAME, json.dumps(snapshot, ensure_ascii=False))
            await asyncio.to_thread(_write_atomic, cp_dir / _INFO_NAME, json.dumps(info, ensure_ascii=False, indent=2))
            self._checkpoints[cid] = info
            await asyncio.to_thread(self._save_index)
        if skipped:
            logger.warning("Checkpoint {} skipped {} unreadable file(s) - undo will not revert them", cid, skipped)
        logger.info("Checkpoint saved: {} ({} files)", cid, len(snapshot))
        return f"[ok] checkpoint '{cid}' saved ({len(snapshot)} files)"

    async def restore(self, cid: str) -> str:
        if not _SAFE_CID.match(cid):
            return f"[error] invalid checkpoint id: {cid}"
        cp_dir = self._storage / cid
        if not await asyncio.to_thread(cp_dir.is_dir):
            return f"[error] checkpoint not found: {cid}"
        snapshot_file = cp_dir / _SNAPSHOT_NAME
        if not await asyncio.to_thread(snapshot_file.is_file):
            return f"[error] snapshot data missing for: {cid}"
        try:
            snapshot = await asyncio.to_thread(_read_json, snapshot_file)
        except (json.JSONDecodeError, OSError) as exc:
            return f"[error] cannot read snapshot: {exc}"
        if not isinstance(snapshot, dict):
            return f"[error] snapshot for {cid} is not an object"

        restored = 0
        for rel_path, content in snapshot.items():
            try:
                target = (self._workspace / rel_path).resolve()
                target.relative_to(self._workspace)
            except ValueError:
                logger.warning("Skipping checkpoint path outside workspace: {}", rel_path)
                continue
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(_write_atomic, target, str(content))
            restored += 1
        logger.info("Checkpoint restored: {} ({} files)", cid, restored)
        return f"[ok] checkpoint '{cid}' restored ({restored} files)"

    async def delete(self, cid: str) -> str:
        if not _SAFE_CID.match(cid):
            return f"[error] invalid checkpoint id: {cid}"
        cp_dir = self._storage / cid
        if not cp_dir.is_dir():
            return f"[error] checkpoint not found: {cid}"
        await asyncio.to_thread(shutil.rmtree, cp_dir)
        async with self._state_lock:
            await asyncio.to_thread(self._load_index)
            self._checkpoints.pop(cid, None)
            await asyncio.to_thread(self._save_index)
        return f"[ok] checkpoint '{cid}' deleted"


_checkpoint_manager: CheckpointManager | None = None


def get_checkpoint_manager(workspace: str | None = None) -> CheckpointManager:
    global _checkpoint_manager
    if _checkpoint_manager is None:
        _checkpoint_manager = CheckpointManager(workspace=workspace)
    return _checkpoint_manager


async def checkpoint_save(description: str = "") -> str:
    return await get_checkpoint_manager().save(description)


async def checkpoint_restore(cid: str) -> str:
    return await get_checkpoint_manager().restore(cid)


async def checkpoint_list() -> str:
    cps = get_checkpoint_manager().list()
    if not cps:
        return "(no checkpoints)"
    return "\n".join(f"{cp['id']}: {cp['description']} ({cp['created']})" for cp in cps)
