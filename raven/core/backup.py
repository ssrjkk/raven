from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.memory.base import MemoryTier

if TYPE_CHECKING:
    from raven.core.memory.manager import MemoryManager


async def export_memory(memory: MemoryManager, dest: Path | None = None) -> Path:
    dest = dest or Path("data") / f"memory_backup_{int(time.time())}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {
        "version": 1,
        "exported_at": time.time(),
        "tiers": {},
    }

    tier_map: dict[MemoryTier, Any] = {
        MemoryTier.WORKING: memory.working,
        MemoryTier.SESSION: memory.session,
        MemoryTier.LONG_TERM: memory.long_term,
        MemoryTier.KNOWLEDGE: memory.knowledge,
    }
    for tier, store in tier_map.items():
        try:
            keys = []
            if hasattr(store, "list_keys"):
                keys = await store.list_keys()
            entries = []
            for key in keys:
                value = await store.recall(key)
                if value is not None:
                    entries.append({"key": key, "value": value})
            data["tiers"][tier.value] = entries
        except Exception as e:
            logger.warning("[backup] failed to export tier {}: {}", tier.value, e)

    dest.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.info("[backup] exported {} tiers to {} ({} KB)", len(data["tiers"]), dest, dest.stat().st_size // 1024)
    return dest


async def import_memory(memory: MemoryManager, source: Path) -> dict[str, int]:
    if not source.is_file():
        raise FileNotFoundError(f"Backup file not found: {source}")

    raw = source.read_text(encoding="utf-8")
    try:
        data: dict[str, Any] = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = f"Backup file is not valid JSON: {source}"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = f"Backup file has invalid structure: {source}"
        raise TypeError(msg)
    version = data.get("version", 0)
    if version < 1:
        raise ValueError(f"Unknown backup version: {version}")

    tier_map_import: dict[MemoryTier, Any] = {
        MemoryTier.WORKING: memory.working,
        MemoryTier.SESSION: memory.session,
        MemoryTier.LONG_TERM: memory.long_term,
        MemoryTier.KNOWLEDGE: memory.knowledge,
    }
    counts: dict[str, int] = {}
    for tier_str, entries in data.get("tiers", {}).items():
        try:
            tier = MemoryTier(tier_str)
        except ValueError:
            logger.warning("[backup] unknown tier '{}', skipping", tier_str)
            continue
        store = tier_map_import.get(tier)
        if store is None or not hasattr(store, "store"):
            continue
        for entry in entries:
            key = entry.get("key", "")
            value = entry.get("value", "")
            if key and value:
                try:
                    await store.store(key, value)
                    counts[tier_str] = counts.get(tier_str, 0) + 1
                except Exception as e:
                    logger.warning("[backup] failed to restore '{}' in {}: {}", key, tier_str, e)

    logger.info("[backup] restored {} entries from {}", sum(counts.values()), source)
    return counts


async def list_backups(backup_dir: Path | None = None) -> list[dict[str, Any]]:
    backup_dir = backup_dir or Path("data")
    if not backup_dir.is_dir():
        return []
    backups = []
    for f in sorted(backup_dir.glob("memory_backup_*.json"), reverse=True):
        backups.append(
            {
                "path": str(f),
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
        )
    return backups
