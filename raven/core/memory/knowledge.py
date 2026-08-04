from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.memory.base import MemoryEntry, MemoryTier


class KnowledgeBase:
    """Structured knowledge (entity-relation graph + vector store)."""

    def __init__(self, workspace: Path | None = None):
        self._workspace = workspace or Path(".raven")
        self._graph_path = self._workspace / "knowledge_graph.json"
        self._graph: dict[str, Any] = {"entities": [], "relations": []}
        self._load()

    def _load(self) -> None:
        if self._graph_path.exists():
            try:
                import json

                raw = self._graph_path.read_text(encoding="utf-8")
                self._graph = json.loads(raw)
            except Exception:
                logger.opt(exception=True).warning("[knowledge] failed to load graph")

    def _save(self) -> None:
        try:
            import json

            self._graph_path.parent.mkdir(parents=True, exist_ok=True)
            self._graph_path.write_text(
                json.dumps(self._graph, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.opt(exception=True).warning("[knowledge] failed to save graph")

    async def _save_async(self) -> None:
        await asyncio.to_thread(self._save)

    async def store(self, key: str, value: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        entity_type = meta.get("type", "concept")
        entity = {"id": key, "name": key, "type": entity_type, "metadata": {"description": value, **meta}}
        existing = [e for e in self._graph["entities"] if e["id"] == key]
        if existing:
            existing[0].update(entity)
        else:
            self._graph["entities"].append(entity)
        await self._save_async()

    async def recall(self, key: str) -> str | None:
        for e in self._graph.get("entities", []):
            if e["id"] == key:
                meta = e.get("metadata", {})
                if isinstance(meta, dict):
                    desc = meta.get("description")
                    return desc if isinstance(desc, str) else str(e)
                return str(e)
        return None

    async def delete(self, key: str) -> bool:
        before = len(self._graph.get("entities", []))
        self._graph["entities"] = [e for e in self._graph.get("entities", []) if e["id"] != key]
        self._graph["relations"] = [
            r for r in self._graph.get("relations", []) if r.get("source_id") != key and r.get("target_id") != key
        ]
        if len(self._graph["entities"]) < before:
            await self._save_async()
            return True
        return False

    async def search(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        q = query.lower()
        for e in self._graph.get("entities", []):
            name = e.get("name", "")
            desc = ""
            meta = e.get("metadata", {})
            if isinstance(meta, dict):
                desc = meta.get("description", "")
            if q in name.lower() or q in desc.lower():
                results.append(
                    MemoryEntry(
                        key=e["id"],
                        value=desc or name,
                        tier=MemoryTier.KNOWLEDGE,
                        metadata={"type": e.get("type", "concept"), **(meta if isinstance(meta, dict) else {})},
                    )
                )
            if len(results) >= limit:
                break
        return results

    async def add_relation(self, source: str, target: str, rel_type: str = "related") -> None:
        rel = {"source_id": source, "target_id": target, "rel_type": rel_type}
        self._graph.setdefault("relations", []).append(rel)
        await self._save_async()

    async def get_related(self, entity_id: str) -> list[dict[str, Any]]:
        related: list[dict[str, Any]] = []
        for r in self._graph.get("relations", []):
            if r["source_id"] == entity_id:
                related.append(r)
        return related

    async def list_keys(self) -> list[str]:
        return [e["id"] for e in self._graph.get("entities", [])]

    async def clear(self) -> None:
        self._graph = {"entities": [], "relations": []}
        await self._save_async()
