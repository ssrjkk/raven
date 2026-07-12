from __future__ import annotations

import asyncio
import hmac
import time
import uuid
from collections import defaultdict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.auth.models import Permission, Role
from raven.core.auth.rbac import rbac
from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.errors import AppError, ErrorCode, classify_error
from raven.core.logging import set_correlation_id
from raven.core.metrics import metrics


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0, burst_multiplier: float = 1.5):
        self.max_requests = max_requests
        self.window = window_seconds
        self.burst_multiplier = burst_multiplier
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._blocked: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            if key in self._blocked:
                if now - self._blocked[key] < self.window * 2:
                    return False
                del self._blocked[key]
            cutoff = now - self.window
            bucket = self._buckets[key]
            bucket[:] = [t for t in bucket if t > cutoff]
            burst_limit = int(self.max_requests * self.burst_multiplier)
            if len(bucket) >= burst_limit:
                self._blocked[key] = now
                return False
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

    async def cleanup(self):
        now = time.monotonic()
        cutoff = now - self.window * 2
        blocked_cutoff = now - self.window * 4
        async with self._lock:
            for key in list(self._buckets.keys()):
                self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]
                if not self._buckets[key]:
                    del self._buckets[key]
            for key in list(self._blocked.keys()):
                if now - self._blocked[key] > blocked_cutoff:
                    del self._blocked[key]


rate_limiter = RateLimiter()

PATH_PERMISSIONS: dict[str, Permission] = {
    "/api/admin": Permission.ADMIN_READ,
    "/api/shutdown": Permission.SYSTEM_SHUTDOWN,
    "/api/raven": Permission.ADMIN_WRITE,
    "/api/chaos": Permission.ADMIN_WRITE,
    "/api/plugins": Permission.ADMIN_WRITE,
    "/api/finetune": Permission.ADMIN_WRITE,
    "/api/email/send": Permission.ADMIN_WRITE,
    "/api/github": Permission.ADMIN_WRITE,
    "/api/git": Permission.ADMIN_WRITE,
    "/api/cost": Permission.ADMIN_READ,
    "/api/auth/users": Permission.ADMIN_USERS,
    "/api/secrets": Permission.ADMIN_SECRETS,
    "/api/stream/push": Permission.ADMIN_WRITE,
    "/api/browser": Permission.ADMIN_WRITE,
    "/api/media/generate": Permission.ADMIN_WRITE,
}


async def request_id_middleware(request: Request, call_next):
    cid = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
    set_correlation_id(cid)
    start = time.monotonic()
    response: Response = await call_next(request)
    duration = time.monotonic() - start
    response.headers["X-Correlation-ID"] = cid
    status_group = str(response.status_code)[0] + "xx"
    metrics.inc("http_requests_total", {"method": request.method, "path": request.url.path, "status": status_group})
    metrics.observe("http_request_duration", duration, {"method": request.method, "path": request.url.path})
    logger.info("{} {} {} {}ms", request.method, request.url.path, response.status_code, int(duration * 1000))
    return response


async def rate_limit_middleware(request: Request, call_next):
    if request.method == "GET":
        return await call_next(request)
    client_ip = request.client.host if request.client else request.headers.get("X-Forwarded-For", "unknown")
    allowed = await rate_limiter.check(client_ip)
    if not allowed:
        metrics.inc("http_rate_limited", {"ip": client_ip})
        logger.warning("Rate limit exceeded for {}", client_ip)
        return JSONResponse(status_code=429, content={"error": "Too many requests", "retry_after": 60})
    return await call_next(request)


async def error_handler_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except AppError as e:
        status = {ErrorCode.AUTH_DENIED: 403, ErrorCode.RATE_LIMITED: 429, ErrorCode.NOT_FOUND: 404}.get(e.code, 400)
        await audit_logger.log(AuditEventType.ERROR, "api", request.url.path, detail=e.to_dict())
        return JSONResponse(status_code=status, content=e.to_dict())
    except Exception as e:
        classify_error(e)
        logger.error("Unhandled error: {} {}", type(e).__name__, e)
        return JSONResponse(status_code=500, content={"code": "internal.error", "message": str(e)[:200]})


async def auth_middleware(request: Request, call_next):
    request.state.user_role = Role.USER.value
    request.state.user_id = "anonymous"

    auth_header = request.headers.get("Authorization", "")
    token = request.headers.get("X-Raven-Key", "")

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if token:
        session = token_manager.validate_token(token)
        if session:
            request.state.user_role = session["role"]
            request.state.user_id = session["user_id"]
        elif settings.web_secret_key and hmac.compare_digest(token, settings.web_secret_key):
            request.state.user_role = Role.ADMIN.value
            request.state.user_id = "admin"

    path = request.url.path
    for prefix, required_perm in PATH_PERMISSIONS.items():
        if path.startswith(prefix) and not rbac.has_permission(request.state.user_role, required_perm):
            return JSONResponse(status_code=403, content={"error": "Forbidden", "required": required_perm.value})

    return await call_next(request)


async def input_sanitize_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        content_type = request.headers.get("content-type", "")
        if "json" in content_type:
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(status_code=400, content={"error": "Invalid JSON body"})
            if isinstance(body, dict):
                max_depth = 10

                def _check_depth(obj, depth=0):
                    if depth > max_depth:
                        raise ValueError("Max depth exceeded")
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if not isinstance(k, str):
                                raise ValueError(f"Non-string key: {k}")
                            _check_depth(v, depth + 1)
                    elif isinstance(obj, list):
                        for item in obj:
                            _check_depth(item, depth + 1)

                try:
                    _check_depth(body)
                except ValueError as e:
                    return JSONResponse(status_code=400, content={"error": str(e)})
    return await call_next(request)
