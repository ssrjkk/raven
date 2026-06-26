from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from loguru import logger


class CheckpointManager:
    def __init__(self, workspace: str | None = None, storage_dir: str = "data/checkpoints") -> None:
        self._workspace = Path(workspace or "workspace").expanduser().resolve()
        self._storage = Path(storage_dir).expanduser().resolve()
        self._checkpoints: dict[str, dict[str, Any]] = {}

    def list(self) -> list[dict[str, Any]]:
        self._load_index()
        return [
            {"id": cid, "created": data.get("created", 0), "description": data.get("description", "")}
            for cid, data in self._checkpoints.items()
        ]

    async def save(self, description: str = "") -> str:
        cid = f"cp_{int(time.time())}"
        cp_dir = self._storage / cid
        cp_dir.mkdir(parents=True, exist_ok=True)
        snapshot: dict[str, str] = {}
        for p in self._workspace.rglob("*"):
            if p.is_file():
                try:
                    content = await asyncio.to_thread(p.read_text, encoding="utf-8")
                    snapshot[str(p.relative_to(self._workspace))] = content
                except Exception as exc:
                    logger.debug("Skipping file {}: {}", p, exc)
        info = {
            "created": time.time(),
            "description": description,
            "files": len(snapshot),
            "workspace": str(self._workspace),
        }
        await asyncio.to_thread(
            (cp_dir / "snapshot.json").write_text,
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await asyncio.to_thread(
            (cp_dir / "info.json").write_text,
            json.dumps(info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._checkpoints[cid] = info
        self._save_index()
        logger.info("Checkpoint saved: {} ({} files)", cid, len(snapshot))
        return f"[ok] checkpoint '{cid}' saved ({len(snapshot)} files)"

    async def restore(self, cid: str) -> str:
        cp_dir = self._storage / cid
        if not cp_dir.is_dir():
            return f"[error] checkpoint not found: {cid}"
        snapshot_file = cp_dir / "snapshot.json"
        if not snapshot_file.is_file():
            return f"[error] snapshot data missing for: {cid}"
        try:
            snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return f"[error] cannot read snapshot: {exc}"
        restored = 0
        for rel_path, content in snapshot.items():
            target = self._workspace / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_text, content, encoding="utf-8")
            restored += 1
        logger.info("Checkpoint restored: {} ({} files)", cid, restored)
        return f"[ok] checkpoint '{cid}' restored ({restored} files)"

    async def delete(self, cid: str) -> str:
        cp_dir = self._storage / cid
        if not cp_dir.is_dir():
            return f"[error] checkpoint not found: {cid}"
        await asyncio.to_thread(shutil.rmtree, cp_dir)
        self._checkpoints.pop(cid, None)
        self._save_index()
        return f"[ok] checkpoint '{cid}' deleted"

    def _load_index(self) -> None:
        idx = self._storage / "index.json"
        if idx.is_file():
            try:
                self._checkpoints = json.loads(idx.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._checkpoints = {}

    def _save_index(self) -> None:
        self._storage.mkdir(parents=True, exist_ok=True)
        idx = self._storage / "index.json"
        idx.write_text(json.dumps(self._checkpoints, ensure_ascii=False, indent=2), encoding="utf-8")


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
