from __future__ import annotations

import asyncio
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
        self._cache: dict[str, dict[str, str]] = {cat: self._parse_file(path) for cat, path in self._files.items()}

    @staticmethod
    def _parse_file(path: Path) -> dict[str, str]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        parsed: dict[str, str] = {}
        for line in text.splitlines():
            if line.startswith("## "):
                key, sep, val = line[3:].partition(": ")
                if sep:
                    parsed[key] = val
        return parsed

    def _dump_category(self, category: str) -> str:
        return "\n".join(f"## {k}: {v}" for k, v in self._cache[category].items())

    @staticmethod
    async def _read_text(path: Path) -> str:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    @staticmethod
    async def _write_text(path: Path, content: str) -> None:
        await asyncio.to_thread(path.write_text, content, encoding="utf-8")

    def _category_for(self, key: str) -> str:
        for cat in ("user", "project", "lessons"):
            if key.startswith(f"{cat}:"):
                return cat
        return "general"

    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        category = self._category_for(key)
        self._cache[category][key] = value[:500]
        try:
            await self._write_text(self._files[category], self._dump_category(category))
        except Exception:
            logger.opt(exception=True).warning("[long_term] store failed for {}", key)

    async def recall(self, key: str) -> str | None:
        category = self._category_for(key)
        return self._cache[category].get(key)

    async def delete(self, key: str) -> bool:
        category = self._category_for(key)
        if key not in self._cache[category]:
            return False
        del self._cache[category][key]
        try:
            await self._write_text(self._files[category], self._dump_category(category))
            return True
        except Exception:
            logger.opt(exception=True).warning("[long_term] delete failed for {}", key)
            return False

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        q = query.lower()
        try:
            for cat, entries in self._cache.items():
                for key, value in entries.items():
                    if q in f"## {key}: {value}".lower():
                        results.append(
                            MemoryEntry(
                                key=key,
                                value=value,
                                tier=MemoryTier.LONG_TERM,
                                metadata={"category": cat},
                            )
                        )
                        if len(results) >= limit:
                            return results
        except Exception:
            logger.opt(exception=True).warning("[long_term] search failed")
        return results[:limit]

    async def list_keys(self) -> list[str]:
        keys: list[str] = []
        for entries in self._cache.values():
            keys.extend(entries)
        return keys

    async def clear(self) -> None:
        for category, path in self._files.items():
            self._cache[category].clear()
            await self._write_text(path, "")

    @property
    def root(self) -> Path:
        return self._root
