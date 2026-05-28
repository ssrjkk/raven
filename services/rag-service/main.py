from __future__ import annotations

import os
import time

import uvicorn
from fastapi import FastAPI
from loguru import logger

app = FastAPI(title="RAG Service", version="1.0.0")
started_at = 0.0
_docs: dict[str, str] = {}


@app.on_event("startup")
async def startup():
    global started_at
    started_at = time.time()
    logger.info("rag-service started")


@app.on_event("shutdown")
async def shutdown():
    logger.info("rag-service shutdown")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "rag-service",
        "docs_indexed": len(_docs),
        "uptime": round(time.time() - started_at, 1),
    }


@app.get("/ready")
async def ready():
    return {"status": "ready", "docs_indexed": len(_docs)}


@app.get("/metrics")
async def metrics():
    return {
        "docs_indexed": len(_docs),
        "uptime_seconds": round(time.time() - started_at, 1),
    }


@app.get("/api/v1/rag/search")
async def search(q: str, limit: int = 5):
    logger.info("RAG search: q='{}' limit={}", q, limit)
    results = []
    for doc_id, content in _docs.items():
        if q.lower() in content.lower():
            results.append({"id": doc_id, "snippet": content[:200]})
            if len(results) >= limit:
                break
    return {"query": q, "results": results, "total": len(results)}


@app.post("/api/v1/rag/index")
async def index(request: dict):
    doc_id = request.get("id", str(time.time()))
    content = request.get("content", "")
    if content:
        _docs[doc_id] = content
    logger.info("RAG index: id={} content_len={}", doc_id, len(content))
    return {"status": "indexed", "document_id": doc_id, "total_docs": len(_docs)}


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
