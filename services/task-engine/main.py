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
    setup_logging(service="task-engine")
    init_otel(service_name="task-engine")
    logger.info("task-engine starting on port {}", os.environ.get("SERVICE_PORT", "8005"))
    yield
    logger.info("task-engine shutting down")


app = FastAPI(title="Raven Task Engine Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "task-engine"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "task-engine"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "task-engine"})
