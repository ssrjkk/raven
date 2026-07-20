from __future__ import annotations

import asyncio
import time
from typing import Protocol

from loguru import logger

from raven.core.cache.redis_client import RedisClient


class RateLimiterProtocol(Protocol):
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool: ...


class InMemoryRateLimiter:
    _IDLE_TTL = 600.0

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        async with self._lock:
            now = time.monotonic()
            window_start = now - window_seconds
            self._evict_stale(window_start)
            entries = self._windows.get(key)
            if entries is None:
                self._windows[key] = [now]
                return True
            self._windows[key] = [t for t in entries if t > window_start]
            if len(self._windows[key]) >= limit:
                return False
            self._windows[key].append(now)
            return True

    def clear(self) -> None:
        self._windows.clear()

    def _evict_stale(self, cutoff: float) -> None:
        stale = [k for k, v in self._windows.items() if v and v[-1] < cutoff]
        for k in stale:
            del self._windows[k]


class RedisRateLimiter:
    def __init__(self, redis_client: RedisClient, fallback: RateLimiterProtocol) -> None:
        self._redis = redis_client
        self._fallback = fallback

    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        if not self._redis.is_healthy:
            return await self._fallback.is_allowed(key, limit, window_seconds)

        client = self._redis._client
        if client is None:
            return await self._fallback.is_allowed(key, limit, window_seconds)

        now = time.time()
        window_start = now - window_seconds
        try:
            await self._redis._execute_with_retry("zremrangebyscore", client.zremrangebyscore, key, 0, window_start)
            current = await self._redis._execute_with_retry("zcard", client.zcard, key)
            if current >= limit:
                return False
            await self._redis._execute_with_retry("zadd", client.zadd, key, {str(now): now})
            await self._redis._execute_with_retry("expire", client.expire, key, window_seconds)
            return True
        except Exception as e:
            logger.warning("redis_rate_limiter.fallback", key=key, error=str(e))
            return await self._fallback.is_allowed(key, limit, window_seconds)
