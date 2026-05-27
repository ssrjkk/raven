from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from services.observability_sdk import init_otel, setup_logging

from . import routes  # noqa: F401
from .store import AuthStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(service="auth")
    init_otel(service_name="auth")
    app.state.store = AuthStore()
    logger.info("auth service starting on port {}", os.environ.get("SERVICE_PORT", "8001"))
    yield
    logger.info("auth service shutting down")


app = FastAPI(title="Raven Auth Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "service": "auth"}


@app.get("/metrics")
async def metrics():
    return JSONResponse(content={"service": "auth"})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: {}", exc)
    return JSONResponse(status_code=500, content={"error": str(exc)})
