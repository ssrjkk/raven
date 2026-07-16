from __future__ import annotations

import time
from typing import Any

from ravencode.core.feature_flags import feature_flags


class TokenBucket:
    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._burst = float(burst)
        self._tokens = float(burst)
        self._last = time.monotonic()

    def acquire(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._last
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class DistributedRateLimiter:
    def __init__(self, redis_url: str = "") -> None:
        self._redis_url = redis_url
        self._redis: Any = None

    async def _ensure_redis(self) -> Any:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(
                    self._redis_url or "redis://localhost:6379/0",
                    decode_responses=True,
                )
            except ImportError:
                self._redis = None
        return self._redis

    async def is_allowed(self, key: str, limit: int, window: int) -> bool:
        if not feature_flags.is_enabled("redis_rate_limiter"):
            return True

        r = await self._ensure_redis()
        if r is None:
            return True

        now = time.time()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window)
        results = await pipe.execute()
        count = results[2] if len(results) > 2 else 0
        return int(count) <= limit
