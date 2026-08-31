from __future__ import annotations

import asyncio
import time
from typing import Protocol

from loguru import logger

from raven.core.cache.redis_client import RedisClient


class RateLimiterProtocol(Protocol):
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool: ...
    async def is_allowed_weighted(self, key: str, amount: int, limit: int, window_seconds: int) -> bool: ...


class InMemoryRateLimiter:
    _IDLE_TTL = 600.0
    _MAX_KEYS = 100_000

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}
        self._weighted_windows: dict[str, list[tuple[float, int]]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        async with self._lock:
            now = time.monotonic()
            window_start = now - window_seconds
            self._evict_stale(window_start)
            self._evict_newest_if_over_capacity()
            entries = self._windows.get(key)
            if entries is None:
                self._windows[key] = [now]
                return True
            self._windows[key] = [t for t in entries if t > window_start]
            if len(self._windows[key]) >= limit:
                return False
            self._windows[key].append(now)
            return True

    async def is_allowed_weighted(self, key: str, amount: int, limit: int, window_seconds: int) -> bool:
        """Check if `amount` fits within the weighted budget for `key` over `window_seconds`.

        Tracks weighted events (timestamp, amount) instead of simple timestamps.
        Returns True if total sum of amounts within window is below limit.
        """
        async with self._lock:
            now = time.monotonic()
            cutoff = now - window_seconds
            entries = self._weighted_windows.get(key)
            if entries is None:
                self._weighted_windows[key] = [(now, amount)]
                return amount <= limit
            self._weighted_windows[key] = [(t, a) for t, a in entries if t > cutoff]
            total = sum(a for _, a in self._weighted_windows[key])
            if total + amount > limit:
                return False
            self._weighted_windows[key].append((now, amount))
            return True

    def clear(self) -> None:
        self._windows.clear()
        self._weighted_windows.clear()

    def _evict_newest_if_over_capacity(self) -> None:
        total = len(self._windows) + len(self._weighted_windows)
        if total <= self._MAX_KEYS:
            return
        overflow = total - self._MAX_KEYS
        keys = [k for k in self._windows if k not in self._weighted_windows][:overflow]
        for k in keys:
            del self._windows[k]

    def _evict_stale(self, cutoff: float) -> None:
        stale = [k for k, v in self._windows.items() if v and v[-1] < cutoff]
        for k in stale:
            del self._windows[k]
        stale_w = [k for k, v in self._weighted_windows.items() if v and v[-1][0] < cutoff]
        for k in stale_w:
            del self._weighted_windows[k]


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
