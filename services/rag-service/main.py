from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI
from loguru import logger

app = FastAPI(title="RAG Service", version="1.0.0")
started_at = 0.0


@app.on_event("startup")
async def startup():
    global started_at
    import time
    started_at = time.time()
    logger.info("rag-service started")


@app.get("/health")
async def health():
    import time
    return {"status": "healthy", "service": "rag-service", "uptime": round(time.time() - started_at, 1)}


@app.get("/ready")
async def ready():
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return {"uptime_seconds": round(__import__("time").time() - started_at, 1)}


@app.get("/api/v1/rag/search")
async def search(q: str, limit: int = 5):
    logger.info("RAG search: q='{}' limit={}", q, limit)
    return {"query": q, "results": [], "total": 0}


@app.post("/api/v1/rag/index")
async def index(request: dict):
    doc_id = request.get("id", "")
    content = request.get("content", "")
    logger.info("RAG index: id={} content_len={}", doc_id, len(content))
    return {"status": "indexed", "document_id": doc_id}


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8004"))
    uvicorn.run(app, host="0.0.0.0", port=port)
