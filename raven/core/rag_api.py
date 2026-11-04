from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.core.events import EventBus
from raven.core.metrics import metrics
from raven.unique.multi_modal_rag import Document, MultiModalRAG

_RAG_PATH = Path(__file__).parent.parent / "data" / "rag_index.json"

# One engine per process. Constructing it loads the embedding models, and every route
# used to build a fresh one, so each request paid for a model it already had.
_rag_engine: MultiModalRAG | None = None
_rag_path: Path | None = None
_rag_mtime: float | None = None


def _get_rag() -> MultiModalRAG:
    global _rag_engine, _rag_path, _rag_mtime
    if _rag_engine is None or _rag_path != _RAG_PATH:
        _rag_engine = MultiModalRAG()
        _rag_engine.set_index_path(str(_RAG_PATH))
        _rag_path = _RAG_PATH
        _rag_mtime = None
    mtime = _RAG_PATH.stat().st_mtime if _RAG_PATH.exists() else None
    if mtime != _rag_mtime:
        _rag_mtime = mtime
        if mtime is not None:
            try:
                _rag_engine.load_index()
            except Exception as e:
                logger.warning("Failed to load RAG index: {}", e)
    return _rag_engine


def _save_rag(rag: MultiModalRAG) -> None:
    global _rag_mtime
    _RAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rag.save_index()
    # The engine in memory is the one that was just written; do not reload it.
    _rag_mtime = _RAG_PATH.stat().st_mtime if _RAG_PATH.exists() else None


class IndexTextRequest(BaseModel):
    document_id: str
    text: str
    source: str = ""
    metadata: str = ""


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    include_images: bool = True


class RemoveDocumentRequest(BaseModel):
    document_id: str


def create_rag_router(event_bus: EventBus | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/rag", tags=["rag"])

    @router.post("/index")
    async def index_text(req: IndexTextRequest):
        rag = _get_rag()
        meta: dict[str, Any] = {}
        if req.metadata:
            try:
                import json

                meta = json.loads(req.metadata)
            except json.JSONDecodeError:
                meta = {"note": req.metadata}
        doc = Document(id=req.document_id, text=req.text, source=req.source, metadata=meta)
        start = time.monotonic()
        chunk_ids = rag.index_document(doc)
        _save_rag(rag)
        metrics.observe("rag_index", time.monotonic() - start)
        metrics.inc("rag_index_document")
        if event_bus is not None:
            await event_bus.publish(
                "rag.indexed",
                document_id=req.document_id,
                chunks=len(chunk_ids),
            )
        return {"document_id": req.document_id, "chunks": len(chunk_ids)}

    @router.post("/search")
    def search(req: SearchRequest):
        rag = _get_rag()
        start = time.monotonic()
        try:
            results = rag.search(req.query, top_k=req.top_k, include_images=req.include_images)
            metrics.observe("rag_search", time.monotonic() - start)
        except Exception as e:
            metrics.error("rag_search", {})
            logger.error("RAG search error: {}", e)
            raise internal_error(e) from e
        return {
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "text": r.text[:500],
                    "score": r.score,
                    "modality": r.modality,
                    "image_path": r.image_path,
                    "citation": {
                        "source": r.citation.source if r.citation else "",
                        "page": r.citation.page if r.citation else 0,
                        "modality": r.citation.modality if r.citation else "",
                    }
                    if r.citation
                    else None,
                }
                for r in results
            ]
        }

    @router.get("/stats")
    def stats():
        rag = _get_rag()
        return rag.get_stats()

    @router.post("/remove")
    def remove_document(req: RemoveDocumentRequest):
        rag = _get_rag()
        if rag.remove_document(req.document_id):
            _save_rag(rag)
            return {"success": True, "document_id": req.document_id}
        raise HTTPException(404, f"Document '{req.document_id}' not found")

    return router
