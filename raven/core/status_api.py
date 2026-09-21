from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.health import health
from raven.core.metrics import metrics

if TYPE_CHECKING:
    from raven.core.gateway.gateway import Gateway
    from raven.core.plugin_loader import PluginLoader


class AgentAssign(BaseModel):
    agent_id: str = "default"


class RavenRequest(BaseModel):
    action: str
    code: str = ""
    context: str = ""


def create_status_router(gateway: Gateway, plugin_loader: PluginLoader, stop_event: asyncio.Event) -> APIRouter:
    router = APIRouter()

    @router.get("/api/status")
    async def api_status():
        return {
            "status": "running",
            "channels": await gateway.channels.list_ids(),
            "plugins": len(plugin_loader.tools),
            "agents": gateway.registry.list_agents(),
            "model": settings.default_model,
            "version": "1.0.0",
        }

    @router.get("/api/agents")
    def api_agents():
        return gateway.registry.list_agents()

    @router.get("/api/health")
    async def api_health():
        return await health.check_all()

    @router.get("/api/health/ready")
    async def api_ready():
        return await health.check_readiness()

    @router.get("/api/health/live")
    def api_live():
        return {"status": "ok"}

    @router.get("/api/metrics")
    def api_metrics():
        return metrics.snapshot()

    @router.get("/api/metrics/prometheus")
    def api_metrics_prometheus():
        return PlainTextResponse(metrics.prometheus())

    @router.post("/api/shutdown")
    async def api_shutdown():
        logger.info("Shutdown requested via API")
        await audit_logger.sensitive("shutdown", "api", "system", True)
        stop_event.set()
        return {"ok": True}

    @router.post("/api/raven")
    async def api_raven(body: RavenRequest):
        logger.info("Raven API call: action={}", body.action)
        await audit_logger.log(AuditEventType.COMMAND, "api", "raven", detail={"action": body.action})
        try:
            session = await gateway.db.get_or_create_session(f"vscode:{body.action}:default", "vscode", "vscode_user")
            agent_obj = gateway.registry.create_agent(session)
            full = ""
            async for token in agent_obj.run(f"{body.action}:\n{body.code[:2000]}\n\nContext: {body.context[:500]}"):
                full += token
            return {"response": full[:5000]}
        except Exception as e:
            logger.error("Raven API error: {}", e)
            raise internal_error(e) from e

    @router.post("/api/sessions/{session_id}/agent")
    def api_set_agent(session_id: str, body: AgentAssign):
        logger.info("Session {} → agent {}", session_id, body.agent_id)
        return {"ok": True, "session_id": session_id, "agent_id": body.agent_id}

    return router
