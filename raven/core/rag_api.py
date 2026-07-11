from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.unique.multi_modal_rag import Document, MultiModalRAG

_RAG_PATH = Path(__file__).parent.parent / "data" / "rag_index.json"


def _get_rag() -> MultiModalRAG:
    rag = MultiModalRAG()
    rag.set_index_path(str(_RAG_PATH))
    if _RAG_PATH.exists():
        try:
            rag.load_index()
        except Exception as e:
            logger.warning("Failed to load RAG index: {}", e)
    return rag


def _save_rag(rag: MultiModalRAG) -> None:
    _RAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rag.save_index()


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


def create_rag_router() -> APIRouter:
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
        chunk_ids = rag.index_document(doc)
        _save_rag(rag)
        return {"document_id": req.document_id, "chunks": len(chunk_ids)}

    @router.post("/search")
    async def search(req: SearchRequest):
        rag = _get_rag()
        try:
            results = rag.search(req.query, top_k=req.top_k, include_images=req.include_images)
        except Exception as e:
            logger.error("RAG search error: {}", e)
            raise HTTPException(500, str(e)) from e
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
                    } if r.citation else None,
                }
                for r in results
            ]
        }

    @router.get("/stats")
    async def stats():
        rag = _get_rag()
        return rag.get_stats()

    @router.post("/remove")
    async def remove_document(req: RemoveDocumentRequest):
        rag = _get_rag()
        if rag.remove_document(req.document_id):
            _save_rag(rag)
            return {"success": True, "document_id": req.document_id}
        raise HTTPException(404, f"Document '{req.document_id}' not found")

    return router
