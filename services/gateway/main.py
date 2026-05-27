from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from loguru import logger

from services.observability_sdk import init_otel, setup_logging

from . import routes  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(service="gateway")
    init_otel(service_name="gateway")
    logger.info("gateway service starting on port {}", os.environ.get("SERVICE_PORT", "8000"))
    yield
    logger.info("gateway service shutting down")


app = FastAPI(title="Raven Gateway Service", version="1.0.0", lifespan=lifespan, docs_url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gateway"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "gateway"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "gateway"})
