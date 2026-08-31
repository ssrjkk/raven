from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from raven.core.admin.models import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthUpdateRoleRequest,
    ConfigUpdateRequest,
    MonitorCreateRequest,
    MonitorUpdateRequest,
    SecretRequest,
    SSEPushRequest,
)
from raven.core.api_errors import internal_error
from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.health import health
from raven.core.jobs import job_manager
from raven.core.metrics import metrics
from raven.core.secrets import secrets
from raven.core.workflow import BUILTIN_TEMPLATES, WorkflowStore
from raven.core.workflow.models import TemplateStep

_workflow_store = WorkflowStore()
_workflow_store.register_many(BUILTIN_TEMPLATES)


class StepInput(BaseModel):
    description: str
    tool: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepsRequest(BaseModel):
    steps: list[StepInput]


def create_admin_router(get_channels_fn, get_registry_fn, get_gateway_fn) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    # -- Monitor CRUD --

    @router.get("/monitors")
    async def admin_monitors_list(user_id: str | None = None):
        gateway = get_gateway_fn()
        store = gateway._monitor_store
        monitors = await store.list_monitors(user_id=user_id)
        return [
            {
                "id": m.id,
                "name": m.name,
                "type": m.type.value,
                "target": m.target,
                "interval_seconds": m.interval_seconds,
                "status": m.status.value,
                "last_check": {"status": m.last_check.status, "checked_at": m.last_check.checked_at}
                if m.last_check
                else None,
                "conditions": [
                    {"metric": c.metric, "operator": c.operator.value, "value": c.value} for c in m.conditions
                ],
                "user_id": m.user_id,
                "channel": m.channel,
                "cooldown_minutes": m.cooldown_minutes,
            }
            for m in monitors
        ]

    @router.get("/monitors/{monitor_id}")
    async def admin_monitor_get(monitor_id: str):
        gateway = get_gateway_fn()
        store = gateway._monitor_store
        m = await store.load_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")
        return {
            "id": m.id,
            "name": m.name,
            "type": m.type.value,
            "target": m.target,
            "interval_seconds": m.interval_seconds,
            "status": m.status.value,
            "last_check": {"status": m.last_check.status, "checked_at": m.last_check.checked_at}
            if m.last_check
            else None,
            "conditions": [{"metric": c.metric, "operator": c.operator.value, "value": c.value} for c in m.conditions],
            "user_id": m.user_id,
            "channel": m.channel,
            "cooldown_minutes": m.cooldown_minutes,
        }

    @router.post("/monitors")
    async def admin_monitor_create(body: MonitorCreateRequest):
        gateway = get_gateway_fn()
        from raven.core.monitor.models import Condition, ConditionOperator, Monitor, MonitorStatus, MonitorType

        store = gateway._monitor_store
        conditions = [
            Condition(metric=c.metric, operator=ConditionOperator(c.operator), value=c.value) for c in body.conditions
        ]
        monitor = Monitor(
            name=body.name,
            type=MonitorType(body.type),
            target=body.target,
            interval_seconds=body.interval_seconds,
            status=MonitorStatus(body.status),
            conditions=conditions,
            user_id=body.user_id,
            channel=body.channel,
            cooldown_minutes=body.cooldown_minutes,
            config=body.config,
        )
        await store.save_monitor(monitor)
        await audit_logger.log(AuditEventType.COMMAND, "admin", "monitor.create", detail={"monitor_id": monitor.id})
        return {"ok": True, "id": monitor.id}

    @router.put("/monitors/{monitor_id}")
    async def admin_monitor_update(monitor_id: str, body: MonitorUpdateRequest):
        gateway = get_gateway_fn()
        from raven.core.monitor.models import Condition, ConditionOperator, MonitorStatus, MonitorType

        store = gateway._monitor_store
        existing = await store.load_monitor(monitor_id)
        if not existing:
            raise HTTPException(404, "Monitor not found")
        if body.name is not None:
            existing.name = body.name
        if body.type is not None:
            existing.type = MonitorType(body.type)
        if body.target is not None:
            existing.target = body.target
        if body.interval_seconds is not None:
            existing.interval_seconds = body.interval_seconds
        if body.status is not None:
            existing.status = MonitorStatus(body.status)
        if body.user_id is not None:
            existing.user_id = body.user_id
        if body.channel is not None:
            existing.channel = body.channel
        if body.cooldown_minutes is not None:
            existing.cooldown_minutes = body.cooldown_minutes
        if body.config is not None:
            existing.config = body.config
        if body.conditions is not None:
            existing.conditions = [
                Condition(metric=c.metric, operator=ConditionOperator(c.operator), value=c.value)
                for c in body.conditions
            ]
        await store.save_monitor(existing)
        await audit_logger.log(AuditEventType.COMMAND, "admin", "monitor.update", detail={"monitor_id": monitor_id})
        return {"ok": True}

    @router.delete("/monitors/{monitor_id}")
    async def admin_monitor_delete(monitor_id: str):
        gateway = get_gateway_fn()
        store = gateway._monitor_store
        m = await store.load_monitor(monitor_id)
        if not m:
            raise HTTPException(404, "Monitor not found")
        await store.delete_monitor(monitor_id)
        await audit_logger.log(AuditEventType.COMMAND, "admin", "monitor.delete", detail={"monitor_id": monitor_id})
        return {"ok": True}

    @router.post("/monitors/{monitor_id}/check")
    async def admin_monitor_check_now(monitor_id: str):
        from raven.core.monitor.engine import MonitorEngine

        gateway = get_gateway_fn()
        store = gateway._monitor_store
        engine = MonitorEngine(store, send_fn=lambda cid, txt: logger.info("Alert[{}]: {}", cid, txt))
        alert_text = await engine.check_now(monitor_id)
        return {"ok": True, "alert": alert_text}

    @router.post("/monitors/{monitor_id}/pause")
    async def admin_monitor_pause(monitor_id: str):
        gateway = get_gateway_fn()
        engine = getattr(gateway, "_monitor_engine", None)
        if engine:
            await engine.pause_monitor(monitor_id)
        return {"ok": True}

    @router.post("/monitors/{monitor_id}/resume")
    async def admin_monitor_resume(monitor_id: str):
        gateway = get_gateway_fn()
        engine = getattr(gateway, "_monitor_engine", None)
        if engine:
            await engine.resume_monitor(monitor_id)
        return {"ok": True}

    @router.get("/health")
    async def admin_health():
        return await health.check_all()

    @router.get("/health/ready")
    async def admin_ready():
        return await health.check_readiness()

    @router.get("/metrics")
    def admin_metrics():
        return metrics.snapshot()

    @router.get("/metrics/prometheus")
    def admin_metrics_prometheus():
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(metrics.prometheus())

    @router.get("/channels")
    def admin_channels():
        channels = get_channels_fn()
        return [
            {
                "id": cid,
                "type": type(ch).__name__,
                "ready": ch._ready if hasattr(ch, "_ready") else True,
                "stats": ch.stats() if hasattr(ch, "stats") else {},
            }
            for cid, ch in channels.items()
        ]

    @router.get("/channels/{channel_id}")
    def admin_channel(channel_id: str):
        channels = get_channels_fn()
        ch = channels.get(channel_id)
        if not ch:
            raise HTTPException(404, "Channel not found")
        return {
            "id": channel_id,
            "type": type(ch).__name__,
            "ready": ch._ready if hasattr(ch, "_ready") else False,
            "stats": ch.stats() if hasattr(ch, "stats") else {},
        }

    @router.post("/channels/{channel_id}/restart")
    async def admin_channel_restart(channel_id: str):
        channels = get_channels_fn()
        ch = channels.get(channel_id)
        if not ch:
            raise HTTPException(404, "Channel not found")
        try:
            await ch.stop()
            await ch.start()
            await audit_logger.log(AuditEventType.CHANNEL_START, "admin", channel_id)
            return {"ok": True, "channel": channel_id}
        except Exception as e:
            raise internal_error(e) from e

    @router.get("/agents")
    def admin_agents():
        registry = get_registry_fn()
        return registry.list_agents()

    @router.post("/agents/{agent_id}/reload")
    def admin_agent_reload(agent_id: str):
        registry = get_registry_fn()
        try:
            registry.setup_defaults()
            return {"ok": True, "agent": agent_id}
        except Exception as e:
            raise internal_error(e) from e

    @router.get("/sessions")
    async def admin_sessions(limit: int = 50, offset: int = 0):
        gateway = get_gateway_fn()
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)
        sessions = await gateway.db.get_sessions()
        page = sessions[offset : offset + limit]
        return [{"id": s.id, "channel": s.channel, "user_id": s.user_id} for s in page]

    @router.get("/audit")
    def admin_audit(limit: int = 50):
        return audit_logger.recent(limit)

    @router.get("/audit/stats")
    def admin_audit_stats():
        return audit_logger.stats()

    @router.get("/audit/verify")
    def admin_audit_verify():
        chain = audit_logger.verify_chain()
        sigs = audit_logger.verify_signatures()
        return {"chain": chain, "signatures": sigs}

    @router.get("/config")
    def admin_config():
        return {
            "model": settings.default_model,
            "web_port": settings.web_port,
            "dm_policy": settings.dm_policy,
            "rate_limit_max": settings.rate_limit_max,
            "log_level": settings.log_level,
            "json_log": settings.json_log,
        }

    @router.get("/secrets")
    async def admin_secrets(request: Request):
        user_role = getattr(request.state, "user_role", None)
        if user_role not in ("admin", "superadmin"):
            raise HTTPException(403, "Secrets require admin role")
        return {"keys": secrets.list_keys()}

    @router.post("/secrets/{key}")
    async def admin_set_secret(key: str, body: SecretRequest, request: Request):
        user_role = getattr(request.state, "user_role", None)
        if user_role not in ("admin", "superadmin"):
            raise HTTPException(403, "Secrets require admin role")
        await secrets.set(key, body.value)
        await audit_logger.sensitive("secrets.set", "admin", key, True)
        return {"ok": True}

    @router.delete("/secrets/{key}")
    async def admin_delete_secret(key: str, request: Request):
        user_role = getattr(request.state, "user_role", None)
        if user_role not in ("admin", "superadmin"):
            raise HTTPException(403, "Secrets require admin role")
        await secrets.unset(key)
        return {"ok": True}

    @router.get("/workflows")
    def admin_workflows(category: str | None = None):
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "category": t.category.value,
                "trigger": t.trigger.value,
                "icon": t.icon,
                "default_schedule": t.default_schedule,
                "default_interval": t.default_interval,
                "config_schema": t.config_schema,
                "steps_goal": t.steps_goal,
                "predefined_steps": [
                    {"description": s.description, "tool": s.tool, "params": s.params}
                    for s in (t.predefined_steps or [])
                ],
            }
            for t in _workflow_store.list_templates(category=category)
        ]

    @router.get("/workflows/{template_id}")
    def admin_workflow_detail(template_id: str):
        t = _workflow_store.get(template_id)
        if not t:
            raise HTTPException(404, "Template not found")
        return t.to_dict()

    @router.get("/workflow-categories")
    def admin_workflow_categories():
        return {"categories": _workflow_store.list_categories()}

    @router.put("/workflows/{template_id}/steps")
    def admin_workflow_update_steps(template_id: str, req: WorkflowStepsRequest):
        t = _workflow_store.get(template_id)
        if not t:
            raise HTTPException(404, "Template not found")
        steps: list[TemplateStep] = [
            TemplateStep(description=s.description, tool=s.tool, params=s.params) for s in req.steps
        ]
        _workflow_store.register(replace(t, predefined_steps=steps))
        logger.info("Admin updated {} steps for workflow '{}'", len(steps), template_id)
        return t.to_dict()

    @router.post("/workflows/{template_id}/generate-steps")
    def admin_workflow_generate_steps(template_id: str):
        t = _workflow_store.get(template_id)
        if not t:
            raise HTTPException(404, "Template not found")
        goal = t.steps_goal or t.description
        lines = [ln.strip().lstrip("-• ") for ln in goal.splitlines() if ln.strip()]
        if len(lines) < 2:
            lines = [ln.strip() for ln in goal.split(".") if ln.strip()][:6]
        steps: list[dict[str, Any]] = [{"description": ln, "tool": None, "params": {}} for ln in lines if ln]
        return {"steps": steps}

    @router.get("/jobs")
    def admin_jobs(status: str | None = None):
        return job_manager.list(status)

    @router.delete("/jobs/{job_id}")
    async def admin_cancel_job(job_id: str):
        ok = await job_manager.cancel(job_id)
        return {"ok": ok}

    @router.post("/shutdown")
    async def admin_shutdown(request: Request):
        user_role = getattr(request.state, "user_role", None)
        if user_role not in ("admin", "superadmin"):
            raise HTTPException(403, "Shutdown requires admin role")
        logger.warning("Admin shutdown requested")
        await audit_logger.log(AuditEventType.SYSTEM_SHUTDOWN, "admin", "system")
        stop_event = request.app.state.stop_event if hasattr(request.app.state, "stop_event") else None
        if stop_event:
            stop_event.set()
        return {"ok": True}

    @router.get("/system/status")
    def admin_system_status():
        gateway = get_gateway_fn()
        channels = get_channels_fn()
        return {
            "channels": len(channels),
            "agents": len(get_registry_fn().list_agents()),
            "running": gateway._running if hasattr(gateway, "_running") else False,
            "version": "1.0.0",
        }

    @router.get("/logs/stream")
    async def admin_logs_stream():
        import asyncio
        import json
        import time

        from fastapi.responses import StreamingResponse

        async def event_generator():
            from collections import deque

            buf: deque[str] = deque(maxlen=50)
            while True:
                log_core = getattr(logger, "_core", None)
                if log_core:
                    for handler in log_core.handlers.values():
                        if hasattr(handler, "stream") and hasattr(handler.stream, "getvalue"):
                            try:
                                new_lines = handler.stream.getvalue().splitlines()
                                for line in new_lines:
                                    buf.append(line)
                            except Exception as exc:
                                logger.warning("Log capture failed: {}", exc)
                if buf:
                    while buf:
                        line = buf.popleft()
                        yield f"data: {json.dumps({'timestamp': time.strftime('%H:%M:%S'), 'level': 'INFO', 'message': line})}\n\n"
                else:
                    yield f"data: {json.dumps({'timestamp': time.strftime('%H:%M:%S'), 'level': 'INFO', 'message': 'heartbeat'})}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @router.get("/auth/oauth/providers")
    def oauth_providers():
        from raven.core.auth.oauth import get_enabled_providers

        return {"providers": get_enabled_providers()}

    @router.get("/auth/oauth/authorize/{provider}")
    def oauth_authorize(provider: str, redirect_uri: str = ""):
        from raven.core.auth.oauth import get_authorize_url

        base = settings.oauth_redirect_base
        uri = redirect_uri or f"{base}/login"
        url = get_authorize_url(provider, uri)
        if not url:
            raise HTTPException(400, f"OAuth provider '{provider}' not enabled")
        return {"url": url}

    @router.post("/auth/oauth/callback/{provider}")
    async def oauth_callback(provider: str, body: dict[str, str]):
        from raven.core.auth.oauth import handle_callback
        from raven.core.auth.tokens import token_manager

        code = body.get("code", "")
        state = body.get("state", "")
        user_info = await handle_callback(provider, code, state)
        if not user_info:
            raise HTTPException(401, "OAuth authentication failed")
        token = token_manager.create_token(user_info["user_id"], "user")
        if provider == "github" and user_info.get("access_token"):
            access_token = user_info.pop("access_token")
            gh_scope = user_info.pop("scope", "")
            await secrets.set("github_oauth_token", access_token)
            logger.info("Persisted GitHub OAuth token (scope: {})", gh_scope)
        return {"token": token, **user_info}

    @router.post("/config/key")
    async def admin_update_config_key(body: ConfigUpdateRequest, request: Request):
        user_role = getattr(request.state, "user_role", None)
        if user_role not in ("admin", "superadmin"):
            raise HTTPException(403, "Config update requires admin role")
        from raven.core.config_store import config_store

        allowed_config_keys = frozenset({
            "default_model", "dm_policy", "rate_limit_max",
            "log_level", "json_log", "web_port", "context_visibility",
        })
        if body.key not in allowed_config_keys:
            raise HTTPException(403, f"Key '{body.key}' is not in the allowed config keys")
        config_store.set(body.key, body.value)
        config_store.save()
        await audit_logger.log(AuditEventType.COMMAND, "admin", "config.update", detail={"key": body.key})
        return {"ok": True}

    return router


AUTH_ENABLED = False
_auth_store = None


def init_auth_routes(app, db_path: str) -> None:
    global AUTH_ENABLED, _auth_store
    from raven.core.auth.store import AuthStore
    from raven.core.auth.tokens import token_manager

    store = AuthStore(db_path)

    _login_attempts: dict[str, list[float]] = {}
    _last_cleanup: float = 0.0

    def _check_login_rate(ip: str) -> bool:
        import time

        now = time.monotonic()
        nonlocal _last_cleanup
        if now - _last_cleanup > 300:
            stale = [k for k, v in _login_attempts.items() if not v or now - v[-1] > 300]
            for k in stale:
                del _login_attempts[k]
            _last_cleanup = now
        attempts = _login_attempts.get(ip, [])
        attempts[:] = [t for t in attempts if now - t < 60]
        if len(attempts) >= 5:
            return False
        attempts.append(now)
        _login_attempts[ip] = attempts
        return True

    @app.post("/api/auth/login")  # type: ignore[untyped-decorator]
    async def auth_login(body: AuthLoginRequest, request: Request):
        ip = request.client.host if request.client else "unknown"
        if not _check_login_rate(ip):
            raise HTTPException(429, "Too many login attempts. Try again later.")
        user = await store.authenticate(body.username, body.password)
        if not user:
            await audit_logger.log(
                AuditEventType.USER_AUTH,
                body.username,
                "login_failed",
                detail={"ip": ip},
            )
            raise HTTPException(401, "Invalid credentials")
        await audit_logger.log(
            AuditEventType.USER_AUTH,
            body.username,
            "login_success",
            detail={"ip": ip},
        )
        token = token_manager.create_token(user.id, user.role.value)
        return {"token": token, "user_id": user.id, "role": user.role.value, "username": user.username}

    @app.post("/api/auth/register")  # type: ignore[untyped-decorator]
    async def auth_register(body: AuthRegisterRequest, request: Request):
        ip = request.client.host if request.client else "unknown"
        if not _check_login_rate(ip):
            raise HTTPException(429, "Too many registration attempts. Try again later.")
        display = body.display_name or body.username
        existing = await store.get_user(body.username)
        if existing:
            raise HTTPException(409, "Username already exists")
        user = await store.create_user(body.username, body.password, display_name=display)
        token = token_manager.create_token(user.id, user.role.value)
        return {"token": token, "user_id": user.id, "role": user.role.value, "username": user.username}

    @app.get("/api/auth/me")  # type: ignore[untyped-decorator]
    def auth_me(request: Request):
        return {
            "user_id": getattr(request.state, "user_id", "anonymous"),
            "role": getattr(request.state, "user_role", "anonymous"),
        }

    @app.post("/api/auth/logout")  # type: ignore[untyped-decorator]
    def auth_logout(request: Request):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token:
            token_manager.revoke_token(token)
        return {"ok": True}

    @app.get("/api/auth/users")  # type: ignore[untyped-decorator]
    async def auth_list_users(request: Request):
        users = await store.list_users()
        return [
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role": u.role.value,
                "is_active": u.is_active,
            }
            for u in users
        ]

    @app.post("/api/auth/users/{username}/role")  # type: ignore[untyped-decorator]
    async def auth_update_role(username: str, body: AuthUpdateRoleRequest):
        try:
            await store.update_role(username, body.role)
        except ValueError as e:
            raise HTTPException(400, f"Invalid request: {type(e).__name__}") from e
        return {"ok": True}

    @app.post("/api/auth/users/{username}/deactivate")  # type: ignore[untyped-decorator]
    async def auth_deactivate_user(username: str):
        await store.set_active(username, False)
        token_manager.revoke_user_tokens(f"user:{username}")
        return {"ok": True}

    @app.get("/api/stream")  # type: ignore[untyped-decorator]
    async def sse_stream(request: Request, session: str = "default"):
        from raven.core.sse import sse_stream

        async def event_generator():
            async for chunk in sse_stream.stream(session):
                yield chunk

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.post("/api/stream/push")  # type: ignore[untyped-decorator]
    async def sse_push(body: SSEPushRequest):
        from raven.core.sse import sse_stream

        await sse_stream.push(
            event=body.event,
            data=body.data,
            session_id=body.session,
        )
        return {"ok": True}

    AUTH_ENABLED = True
    _auth_store = store
