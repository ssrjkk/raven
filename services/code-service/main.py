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
    setup_logging(service="code-service")
    init_otel(service_name="code-service")
    logger.info("code-service starting on port {}", os.environ.get("SERVICE_PORT", "8006"))
    yield
    logger.info("code-service shutting down")


app = FastAPI(title="Raven Code Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "code-service"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "code-service"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "code-service"})
