from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.health import health
from raven.core.jobs import job_manager
from raven.core.metrics import metrics
from raven.core.secrets import secrets


def create_admin_router(get_channels_fn, get_registry_fn, get_gateway_fn) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/health")
    async def admin_health():
        return await health.check_all()

    @router.get("/health/ready")
    async def admin_ready():
        return await health.check_readiness()

    @router.get("/metrics")
    async def admin_metrics():
        return metrics.snapshot()

    @router.get("/metrics/prometheus")
    async def admin_metrics_prometheus():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(metrics.prometheus())

    @router.get("/channels")
    async def admin_channels():
        channels = get_channels_fn()
        return [
            {"id": cid, "type": type(ch).__name__, "stats": ch.stats() if hasattr(ch, "stats") else {}}
            for cid, ch in channels.items()
        ]

    @router.get("/channels/{channel_id}")
    async def admin_channel(channel_id: str):
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
            audit_logger.log(AuditEventType.CHANNEL_START, "admin", channel_id)
            return {"ok": True, "channel": channel_id}
        except Exception as e:
            raise HTTPException(500, str(e))

    @router.get("/agents")
    async def admin_agents():
        registry = get_registry_fn()
        return registry.list_agents()

    @router.post("/agents/{agent_id}/reload")
    async def admin_agent_reload(agent_id: str):
        registry = get_registry_fn()
        try:
            registry.setup_defaults()
            return {"ok": True, "agent": agent_id}
        except Exception as e:
            raise HTTPException(500, str(e))

    @router.get("/sessions")
    async def admin_sessions(limit: int = 50, offset: int = 0):
        gateway = get_gateway_fn()
        sessions = await gateway.db.get_sessions()
        return [{"id": s.id, "channel": s.channel, "user_id": s.user_id} for s in sessions]

    @router.get("/audit")
    async def admin_audit(limit: int = 50):
        return audit_logger.recent(limit)

    @router.get("/config")
    async def admin_config():
        return {
            "model": settings.default_model,
            "web_port": settings.web_port,
            "dm_policy": settings.dm_policy,
            "rate_limit_max": settings.rate_limit_max,
            "log_level": settings.log_level,
            "json_log": settings.json_log,
        }

    @router.get("/secrets")
    async def admin_secrets():
        return {"keys": secrets.list_keys()}

    @router.post("/secrets/{key}")
    async def admin_set_secret(key: str, body: dict):
        value = body.get("value", "")
        if not value:
            raise HTTPException(400, "value required")
        secrets.set(key, value)
        audit_logger.sensitive("secrets.set", "admin", key, True)
        return {"ok": True}

    @router.delete("/secrets/{key}")
    async def admin_delete_secret(key: str):
        secrets.unset(key)
        return {"ok": True}

    @router.get("/jobs")
    async def admin_jobs(status: str | None = None):
        return job_manager.list(status)

    @router.delete("/jobs/{job_id}")
    async def admin_cancel_job(job_id: str):
        ok = await job_manager.cancel(job_id)
        return {"ok": ok}

    @router.post("/shutdown")
    async def admin_shutdown(request: Request):
        logger.warning("Admin shutdown requested")
        audit_logger.log(AuditEventType.SYSTEM_SHUTDOWN, "admin", "system")
        stop_event = request.app.state.stop_event if hasattr(request.app.state, "stop_event") else None
        if stop_event:
            stop_event.set()
        return {"ok": True}

    @router.get("/system/status")
    async def admin_system_status():
        gateway = get_gateway_fn()
        channels = get_channels_fn()
        return {
            "channels": len(channels),
            "agents": len(get_registry_fn().list_agents()),
            "running": gateway._running if hasattr(gateway, "_running") else False,
            "version": "1.0.0",
        }

    return router


AUTH_ENABLED = False
_auth_store = None


def init_auth_routes(app, db_path: str):
    global AUTH_ENABLED, _auth_store
    from raven.core.auth.store import AuthStore
    from raven.core.auth.tokens import token_manager

    store = AuthStore(db_path)

    @app.post("/api/auth/login")
    async def auth_login(body: dict):
        username = body.get("username", "")
        password = body.get("password", "")
        user = await store.authenticate(username, password)
        if not user:
            from fastapi import HTTPException
            raise HTTPException(401, "Invalid credentials")
        token = token_manager.create_token(user.id, user.role.value)
        return {"token": token, "user_id": user.id, "role": user.role.value, "username": user.username}

    @app.post("/api/auth/register")
    async def auth_register(body: dict):
        username = body.get("username", "")
        password = body.get("password", "")
        display = body.get("display_name", username)
        if not username or not password:
            from fastapi import HTTPException
            raise HTTPException(400, "username and password required")
        existing = await store.get_user(username)
        if existing:
            raise HTTPException(409, "Username already exists")
        user = await store.create_user(username, password, display_name=display)
        token = token_manager.create_token(user.id, user.role.value)
        return {"token": token, "user_id": user.id, "role": user.role.value, "username": user.username}

    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        return {
            "user_id": getattr(request.state, "user_id", "anonymous"),
            "role": getattr(request.state, "user_role", "anonymous"),
        }

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token:
            token_manager.revoke_token(token)
        return {"ok": True}

    @app.get("/api/auth/users")
    async def auth_list_users(request: Request):
        users = await store.list_users()
        return [
            {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role.value, "is_active": u.is_active}
            for u in users
        ]

    @app.post("/api/auth/users/{username}/role")
    async def auth_update_role(username: str, body: dict):
        new_role = body.get("role", "")
        if new_role not in ("admin", "user", "viewer", "banned"):
            from fastapi import HTTPException
            raise HTTPException(400, f"Invalid role: {new_role}")
        await store.update_role(username, new_role)
        return {"ok": True}

    @app.post("/api/auth/users/{username}/deactivate")
    async def auth_deactivate_user(username: str):
        await store.set_active(username, False)
        token_manager.revoke_user_tokens(f"user:{username}")
        return {"ok": True}

    AUTH_ENABLED = True
    _auth_store = store
