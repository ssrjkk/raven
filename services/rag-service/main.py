from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from services.observability_sdk import init_otel, setup_logging

from . import routes  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(service="rag-service")
    init_otel(service_name="rag-service")
    logger.info("rag-service starting on port {}", os.environ.get("SERVICE_PORT", "8004"))
    yield
    logger.info("rag-service shutting down")


app = FastAPI(title="Raven RAG Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "rag-service"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "rag-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "rag-service"})
