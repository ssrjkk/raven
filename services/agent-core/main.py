from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from services.observability_sdk import init_otel, setup_logging

from . import routes  # noqa: F401
from .llm_router import LLMRouter
from .nats_client import NatsClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(service="agent-core")
    init_otel(service_name="agent-core")
    nats = NatsClient()
    await nats.connect()
    app.state.nats = nats
    app.state.llm = LLMRouter()
    logger.info("agent-core service starting on port {}", os.environ.get("SERVICE_PORT", "8002"))
    yield
    await nats.close()
    logger.info("agent-core service shutting down")


app = FastAPI(title="Raven Agent Core Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agent-core"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "agent-core"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "agent-core"})
