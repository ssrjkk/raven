from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

app = FastAPI(title="RAG Service", version="1.0.0")

VECTOR_SIZE = 384
COLLECTION_NAME = "documents"
_NGRAM_RNG = np.random.RandomState(42)
_NGRAM_PROJ = _NGRAM_RNG.randn(VECTOR_SIZE, 256).astype(np.float32)

started_at = 0.0
qdrant: QdrantClient | None = None
_fallback_docs: dict[str, str] = {}


def _embed(text: str) -> list[float]:
    text = text.lower()
    ngram_counts = {}
    for n in range(2, 5):
        for i in range(len(text) - n + 1):
            ng = text[i : i + n]
            idx = int(hashlib.md5(ng.encode()).hexdigest()[:8], 16) % 256
            ngram_counts[idx] = ngram_counts.get(idx, 0) + 1
    vec = np.zeros(VECTOR_SIZE, dtype=np.float32)
    for idx, count in ngram_counts.items():
        vec += _NGRAM_PROJ[:, idx] * count
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec.tolist()


@app.on_event("startup")
async def startup():
    global started_at, qdrant
    started_at = time.time()
    qdrant_url = os.environ.get("QDRANT_URL", "")
    if qdrant_url:
        try:
            qdrant = QdrantClient(url=qdrant_url, timeout=5.0)
            collections = qdrant.get_collections().collections
            if not any(c.name == COLLECTION_NAME for c in collections):
                qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
            logger.info("connected to Qdrant at {}", qdrant_url)
        except Exception as e:
            logger.warning("Qdrant unavailable, using in-memory fallback: {}", e)
            qdrant = None
    else:
        logger.info("no QDRANT_URL set, using in-memory fallback")
    logger.info("rag-service started")


@app.on_event("shutdown")
async def shutdown():
    logger.info("rag-service shutdown")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "service": "rag-service",
        "docs_indexed": len(_fallback_docs),
        "qdrant": qdrant is not None,
        "uptime": round(time.time() - started_at, 1),
    }


@app.get("/ready")
async def ready() -> dict[str, Any]:
    return {"status": "ready", "docs_indexed": len(_fallback_docs)}


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    return {
        "docs_indexed": len(_fallback_docs),
        "uptime_seconds": round(time.time() - started_at, 1),
    }


@app.post("/api/v1/rag/index")
async def index(request: dict[str, Any]) -> dict[str, Any]:
    doc_id = request.get("id", str(time.time()))
    content = request.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    vec = _embed(content)
    if qdrant is not None:
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=doc_id, vector=vec, payload={"content": content, "id": doc_id})],
        )
    else:
        _fallback_docs[doc_id] = content
    logger.info("RAG index: id={} content_len={}", doc_id, len(content))
    return {"status": "indexed", "document_id": doc_id, "total_docs": len(_fallback_docs)}


@app.get("/api/v1/rag/search")
async def search(q: str, limit: int = 5) -> dict[str, Any]:
    if not q:
        raise HTTPException(status_code=400, detail="query is required")
    logger.info("RAG search: q='{}' limit={}", q, limit)
    if qdrant is not None:
        vec = _embed(q)
        hits = qdrant.search(
            collection_name=COLLECTION_NAME,
            query_vector=vec,
            limit=limit,
            with_payload=True,
        )
        results = [
            {
                "id": h.payload.get("id", ""),
                "snippet": (h.payload.get("content", "") or "")[:200],
                "score": round(h.score, 4) if h.score else 0.0,
            }
            for h in hits
        ]
    else:
        query_lower = q.lower()
        results = []
        for doc_id, content in _fallback_docs.items():
            if query_lower in content.lower():
                results.append({"id": doc_id, "snippet": content[:200], "score": 1.0})
                if len(results) >= limit:
                    break
    return {"query": q, "results": results, "total": len(results)}


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
