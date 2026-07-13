from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from raven.core.metrics import metrics


class TokenBucket:
    _IDLE_TTL = 300.0  # evict buckets idle > 5 minutes

    def __init__(self, rate: float = 10.0, burst: int | None = None):
        self._rate = rate
        self._burst = burst or int(rate * 2)
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._last_access = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(float(self._burst), self._tokens + elapsed * self._rate)
            self._last_refill = now
            self._last_access = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def burst(self) -> int:
        return self._burst

    @property
    def last_access(self) -> float:
        return self._last_access


DEFAULT_CHANNEL_LIMITS: dict[str, dict[str, float | int]] = {
    "discord": {"rate": 5.0, "burst": 10},
    "telegram": {"rate": 3.0, "burst": 6},
    "slack": {"rate": 8.0, "burst": 16},
    "webchat": {"rate": 10.0, "burst": 20},
    "default": {"rate": 10.0, "burst": 20},
}

DEFAULT_USER_LIMITS: dict[str, dict[str, float | int]] = {
    "default": {"rate": 5.0, "burst": 10},
}


class RateLimiter:
    def __init__(
        self,
        channel_limits: dict[str, dict[str, float | int]] | None = None,
        user_limits: dict[str, dict[str, float | int]] | None = None,
    ):
        self._channel_limits: dict[str, dict[str, float | int]] = channel_limits or {}
        self._user_limits: dict[str, dict[str, float | int]] = user_limits or {}
        self._channel_buckets: dict[str, TokenBucket] = {}
        self._user_buckets: dict[str, TokenBucket] = {}
        self._type_cache: dict[str, str] = {}

    def set_channel_limit(self, channel_type: str, rate: float, burst: int) -> None:
        self._channel_limits[channel_type] = {"rate": rate, "burst": burst}

    def set_user_limit(self, user_category: str, rate: float, burst: int) -> None:
        self._user_limits[user_category] = {"rate": rate, "burst": burst}

    def get_channel_limit(self, channel_type: str) -> dict[str, float | int]:
        return self._channel_limits.get(
            channel_type,
            self._channel_limits.get("default", DEFAULT_CHANNEL_LIMITS["default"]),
        )

    def get_user_limit(self, user_category: str = "default") -> dict[str, float | int]:
        return self._user_limits.get(user_category, DEFAULT_USER_LIMITS["default"])

    def _get_or_create_channel_bucket(self, channel_id: str, channel_type: str | None = None) -> TokenBucket:
        bucket = self._channel_buckets.get(channel_id)
        if bucket is None:
            ctype = channel_type or self._type_cache.get(channel_id, "default")
            self._type_cache[channel_id] = ctype
            cfg = self.get_channel_limit(ctype)
            bucket = TokenBucket(rate=float(cfg["rate"]), burst=int(cfg["burst"]))
            self._channel_buckets[channel_id] = bucket
        return bucket

    def _get_or_create_user_bucket(self, user_id: str) -> TokenBucket:
        bucket = self._user_buckets.get(user_id)
        if bucket is None:
            cfg = self.get_user_limit("default")
            bucket = TokenBucket(rate=float(cfg["rate"]), burst=int(cfg["burst"]))
            self._user_buckets[user_id] = bucket
        return bucket

    async def check_rate_limit(
        self, channel_id: str, user_id: str | None = None, channel_type: str | None = None
    ) -> bool:
        self._evict_idle()
        cb = self._get_or_create_channel_bucket(channel_id, channel_type)
        if not await cb.acquire():
            logger.warning("Rate limit exceeded for channel {} (type={})", channel_id, channel_type)
            metrics.inc("rate_limiter_blocked", {"scope": "channel", "channel": channel_id})
            return False

        if user_id:
            ub = self._get_or_create_user_bucket(user_id)
            if not await ub.acquire():
                logger.warning("Rate limit exceeded for user {} on channel {}", user_id, channel_id)
                metrics.inc("rate_limiter_blocked", {"scope": "user", "channel": channel_id})
                return False

        return True

    def status(self) -> dict[str, Any]:
        channels = {}
        for cid, bucket in self._channel_buckets.items():
            channels[cid] = {
                "tokens": bucket._tokens,
                "rate": bucket.rate,
                "burst": bucket.burst,
                "type": self._type_cache.get(cid, "unknown"),
            }
        users = {}
        for uid, bucket in self._user_buckets.items():
            users[uid] = {
                "tokens": bucket._tokens,
                "rate": bucket.rate,
                "burst": bucket.burst,
            }
        return {"channels": channels, "users": users}

    def clear(self) -> None:
        self._channel_buckets.clear()
        self._user_buckets.clear()
        self._type_cache.clear()

    def _evict_idle(self) -> None:
        now = time.monotonic()
        idle_cutoff = now - TokenBucket._IDLE_TTL
        stale_channels = [k for k, b in self._channel_buckets.items() if b.last_access < idle_cutoff]
        for k in stale_channels:
            del self._channel_buckets[k]
            self._type_cache.pop(k, None)
        stale_users = [k for k, b in self._user_buckets.items() if b.last_access < idle_cutoff]
        for k in stale_users:
            del self._user_buckets[k]
