from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from raven.unique.knowledge_graph import Document, KnowledgeGraph

_KG_PATH = Path(__file__).parent.parent / "data" / "knowledge_graph.json"


def _get_kg() -> KnowledgeGraph:
    kg = KnowledgeGraph()
    if _KG_PATH.exists():
        try:
            kg.load(_KG_PATH)
        except Exception as e:
            logger.warning("Failed to load KG: {}", e)
    return kg


def _save_kg(kg: KnowledgeGraph) -> None:
    _KG_PATH.parent.mkdir(parents=True, exist_ok=True)
    kg.save(_KG_PATH)


def create_knowledge_router() -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

    @router.post("/extract")
    async def extract(text: str, source: str = ""):
        kg = _get_kg()
        doc = Document(text=text, source=source)
        try:
            result = kg.extract_from_document(doc)
            _save_kg(kg)
            stats = kg.get_stats()
            return {"result": result, "stats": stats}
        except Exception as e:
            logger.error("KG extract error: {}", e)
            raise HTTPException(500, str(e)) from e

    @router.post("/search")
    async def search(query: str, max_depth: int = 2):
        kg = _get_kg()
        stats = kg.get_stats()
        if stats["entities"] == 0:
            return {"results": [], "stats": stats}
        try:
            results = kg.search(query, max_depth=max_depth)
            return {"results": results, "stats": stats}
        except Exception as e:
            logger.error("KG search error: {}", e)
            raise HTTPException(500, str(e)) from e

    @router.get("/stats")
    async def stats():
        kg = _get_kg()
        return kg.get_stats()

    @router.get("/vis")
    async def vis():
        kg = _get_kg()
        data = kg.export_vis()
        stats = kg.get_stats()
        return {"graph": data, "stats": stats}

    @router.post("/entity")
    async def add_entity(name: str, type: str = "concept", metadata: str = ""):
        kg = _get_kg()
        meta: dict[str, Any] = {}
        if metadata:
            try:
                import json
                meta = json.loads(metadata)
            except json.JSONDecodeError:
                meta = {"note": metadata}
        try:
            entity = kg.add_entity(name, type, meta)
            _save_kg(kg)
            return {"entity": {"id": entity.id, "name": entity.name, "type": entity.type}}
        except Exception as e:
            raise HTTPException(500, str(e)) from e

    @router.post("/relation")
    async def add_relation(source: str, target: str, type: str = "related_to"):
        kg = _get_kg()
        source_ent = kg._find_entity(source)
        target_ent = kg._find_entity(target)
        if not source_ent:
            raise HTTPException(404, f"Source entity '{source}' not found")
        if not target_ent:
            raise HTTPException(404, f"Target entity '{target}' not found")
        try:
            rel = kg.add_relation(source_ent.id, target_ent.id, type)
            _save_kg(kg)
            return {"relation": {"id": rel.id, "source": source_ent.name, "target": target_ent.name, "type": rel.rel_type}}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            raise HTTPException(500, str(e)) from e

    return router
