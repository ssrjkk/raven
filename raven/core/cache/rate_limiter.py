from __future__ import annotations

import time
from typing import Protocol

from loguru import logger

from raven.core.cache.redis_client import RedisClient


class RateLimiterProtocol(Protocol):
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool: ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}

    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        window_start = now - window_seconds
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


class RedisRateLimiter:
    def __init__(self, redis_client: RedisClient, fallback: RateLimiterProtocol) -> None:
        self._redis = redis_client
        self._fallback = fallback

    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        if not self._redis.is_healthy:
            return await self._fallback.is_allowed(key, limit, window_seconds)

        now = time.time()
        window_start = now - window_seconds
        try:
            await self._redis._execute_with_retry(
                "zremrangebyscore",
                self._redis._client.zremrangebyscore,  # type: ignore[union-attr]
                key,
                0,
                window_start,
            )
            current = await self._redis._execute_with_retry(
                "zcard",
                self._redis._client.zcard,  # type: ignore[union-attr]
                key,
            )
            if current >= limit:
                return False
            await self._redis._execute_with_retry(
                "zadd",
                self._redis._client.zadd,  # type: ignore[union-attr]
                key,
                {str(now): now},
            )
            await self._redis._execute_with_retry(
                "expire",
                self._redis._client.expire,  # type: ignore[union-attr]
                key,
                window_seconds,
            )
            return True
        except Exception as e:
            logger.warning("redis_rate_limiter.fallback", error=str(e))
            return await self._fallback.is_allowed(key, limit, window_seconds)
