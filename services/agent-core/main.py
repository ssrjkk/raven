from __future__ import annotations

import os
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger

from llm_router import LLMRouter
from nats_client import NATSClient

app = FastAPI(title="Agent Core", version="1.0.0")
if not os.environ.get("LLM_API_KEY"):
    logger.warning("LLM_API_KEY not set — LLM calls will fail")
llm = LLMRouter()
nats = NATSClient()
started_at = 0.0


@app.on_event("startup")
async def startup():
    global started_at
    started_at = time.time()
    nats_url = os.environ.get("NATS_URL", "nats://nats:4222")
    try:
        await nats.connect(nats_url)
        logger.info("agent-core started, NATS connected to {}", nats_url)
    except Exception as e:
        logger.warning("agent-core started without NATS: {}", e)


@app.on_event("shutdown")
async def shutdown():
    await nats.close()
    await llm.close()
    logger.info("agent-core shutdown")


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "agent-core",
        "uptime": round(time.time() - started_at, 1),
    }


@app.get("/ready")
async def ready():
    if not nats.connected:
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "reason": "NATS disconnected"},
        )
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return {
        "llm_calls": llm._metrics,
        "nats_connected": nats.connected,
        "uptime_seconds": round(time.time() - started_at, 1),
    }


@app.post("/api/v1/agent/chat")
async def chat(request: dict, raw_request: Request):
    session_id = request.get("session_id") or str(uuid.uuid4())
    messages = request.get("messages", request.get("message", []))
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]

    logger.info("Chat request: session={} messages={}", session_id, len(messages))

    try:
        result = await llm.chat(messages, session_id=session_id)
    except Exception as e:
        logger.error("LLM chat failed: {}", e)
        return JSONResponse(
            status_code=502, content={"error": "LLM request failed", "detail": str(e)}
        )

    result["session_id"] = session_id

    if nats.connected:
        await nats.publish(
            "agent.response", {"session_id": session_id, "response": result["response"]}
        )

    return result


if __name__ == "__main__":
    port = int(os.environ.get("SERVICE_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
