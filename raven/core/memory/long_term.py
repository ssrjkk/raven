from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.memory.base import MemoryEntry, MemoryTier


class LongTermMemory:
    """File-based persistent facts. Stores in .raven/memory/ as markdown."""

    def __init__(self, workspace: Path | None = None):
        base = workspace or Path(".raven")
        self._root = base / "memory"
        self._root.mkdir(parents=True, exist_ok=True)
        self._files = {
            "user": self._root / "user.md",
            "project": self._root / "project.md",
            "lessons": self._root / "lessons.md",
            "general": self._root / "general.md",
        }
        for f in self._files.values():
            if not f.exists():
                f.write_text("", encoding="utf-8")

    def _category_for(self, key: str) -> str:
        for cat in ("user", "project", "lessons"):
            if key.startswith(f"{cat}:"):
                return cat
        return "general"

    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        category = self._category_for(key)
        path = self._files[category]
        try:
            existing = path.read_text(encoding="utf-8")
            lines = existing.splitlines()
            kept = [line for line in lines if not line.startswith(f"## {key}:")]
            kept.append(f"## {key}: {value[:500]}")
            path.write_text("\n".join(kept), encoding="utf-8")
        except Exception:
            logger.opt(exception=True).warning("[long_term] store failed for {}", key)

    async def recall(self, key: str) -> str | None:
        category = self._category_for(key)
        path = self._files[category]
        try:
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith(f"## {key}:"):
                    return line[len(f"## {key}: "):]
            return None
        except Exception:
            logger.opt(exception=True).warning("[long_term] recall failed for {}", key)
            return None

    async def delete(self, key: str) -> bool:
        category = self._category_for(key)
        path = self._files[category]
        try:
            existing = path.read_text(encoding="utf-8")
            lines = [ln for ln in existing.splitlines() if not ln.startswith(f"## {key}:")]
            path.write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception:
            logger.opt(exception=True).warning("[long_term] delete failed for {}", key)
            return False

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        q = query.lower()
        try:
            for cat, path in self._files.items():
                text = path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if q in line.lower():
                        parts = line.split(": ", 1)
                        key = parts[0].lstrip("# ") if len(parts) > 1 else "unknown"
                        val = parts[1] if len(parts) > 1 else line
                        results.append(
                            MemoryEntry(key=key, value=val, tier=MemoryTier.LONG_TERM, metadata={"category": cat})
                        )
                        if len(results) >= limit:
                            return results
        except Exception:
            logger.opt(exception=True).warning("[long_term] search failed")
        return results[:limit]

    async def list_keys(self) -> list[str]:
        keys: list[str] = []
        try:
            for path in self._files.values():
                text = path.read_text(encoding="utf-8")
                for line in text.splitlines():
                    if line.startswith("## "):
                        key = line.split(":")[0].lstrip("# ")
                        keys.append(key)
        except Exception:
            logger.opt(exception=True).warning("[long_term] list_keys failed")
        return keys

    async def clear(self) -> None:
        for path in self._files.values():
            path.write_text("", encoding="utf-8")

    @property
    def root(self) -> Path:
        return self._root
