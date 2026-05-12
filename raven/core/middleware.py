from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.errors import AppError, ErrorCode, classify_error
from raven.core.logging import set_correlation_id
from raven.core.metrics import metrics


class RateLimiter:
    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        async with self._lock:
            bucket = self._buckets[key]
            bucket[:] = [t for t in bucket if t > cutoff]
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

    async def cleanup(self):
        now = time.monotonic()
        cutoff = now - self.window * 2
        async with self._lock:
            for key in list(self._buckets.keys()):
                self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]
                if not self._buckets[key]:
                    del self._buckets[key]


rate_limiter = RateLimiter()


async def request_id_middleware(request: Request, call_next):
    cid = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
    set_correlation_id(cid)
    start = time.monotonic()
    response: Response = await call_next(request)
    duration = time.monotonic() - start
    response.headers["X-Correlation-ID"] = cid
    metrics.inc("http_requests_total", {"method": request.method, "path": request.url.path, "status": str(response.status_code)})
    metrics.observe("http_request_duration", duration, {"method": request.method, "path": request.url.path})
    logger.info("{} {} {} {}ms", request.method, request.url.path, response.status_code, int(duration * 1000))
    return response


async def rate_limit_middleware(request: Request, call_next):
    if request.method == "GET":
        return await call_next(request)


async def error_handler_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except AppError as e:
        status = {ErrorCode.AUTH_DENIED: 403, ErrorCode.RATE_LIMITED: 429, ErrorCode.NOT_FOUND: 404}.get(e.code, 400)
        audit_logger.log(AuditEventType.ERROR, "api", request.url.path, detail=e.to_dict())
        return JSONResponse(status_code=status, content=e.to_dict())
    except Exception as e:
        classify_error(e)
        logger.error("Unhandled error: {} {}", type(e).__name__, e)
        return JSONResponse(status_code=500, content={"code": "internal.error", "message": str(e)[:200]})
    client_ip = request.client.host if request.client else "unknown"
    allowed = await rate_limiter.check(client_ip)
    if not allowed:
        metrics.inc("http_rate_limited", {"ip": client_ip})
        logger.warning("Rate limit exceeded for {}", client_ip)
        return JSONResponse(status_code=429, content={"error": "Too many requests", "retry_after": 60})
    return await call_next(request)


async def auth_middleware(request: Request, call_next):
    secret_key = settings.web_secret_key
    if secret_key:
        path = request.url.path
        sensitive = ("/api/shutdown", "/api/raven", "/api/agents", "/api/admin")
        if any(path.startswith(p) for p in sensitive):
            auth = request.headers.get("X-Raven-Key", "")
            if auth != secret_key:
                metrics.inc("http_auth_failed", {"path": path})
                return JSONResponse(status_code=403, content={"error": "Forbidden"})
    return await call_next(request)
