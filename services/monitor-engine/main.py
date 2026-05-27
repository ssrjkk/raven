from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from services.observability_sdk import init_otel, setup_logging

from . import routes  # noqa: F401
from .engine import MonitorEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(service="monitor-engine")
    init_otel(service_name="monitor-engine")
    engine = MonitorEngine()
    await engine.start()
    app.state.engine = engine
    logger.info("monitor-engine service starting on port {}", os.environ.get("SERVICE_PORT", "8003"))
    yield
    await engine.stop()
    logger.info("monitor-engine service shutting down")


app = FastAPI(title="Raven Monitor Engine Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "monitor-engine"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "monitor-engine"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "monitor-engine"})
