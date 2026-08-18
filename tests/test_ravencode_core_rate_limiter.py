from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ravencode.core.rate_limiter as rate_limiter_mod
from ravencode.core.rate_limiter import DistributedRateLimiter, TokenBucket


class TestTokenBucket:
    def test_initial_burst_available(self) -> None:
        bucket = TokenBucket(rate=1.0, burst=2)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False

    def test_refill_after_time(self, monkeypatch) -> None:
        clock = [0.0]

        def fake_monotonic() -> float:
            return clock[0]

        monkeypatch.setattr("ravencode.core.rate_limiter.time.monotonic", fake_monotonic)
        bucket = TokenBucket(rate=1.0, burst=2)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False

        clock[0] = 1.5
        assert bucket.acquire() is True

    def test_burst_caps_refill(self, monkeypatch) -> None:
        clock = [0.0]

        def fake_monotonic() -> float:
            return clock[0]

        monkeypatch.setattr("ravencode.core.rate_limiter.time.monotonic", fake_monotonic)
        bucket = TokenBucket(rate=1.0, burst=1)
        assert bucket.acquire() is True
        clock[0] = 100.0
        assert bucket.acquire() is True
        assert bucket.acquire() is False


def _set_flag(monkeypatch, value: bool) -> None:
    monkeypatch.setattr("ravencode.core.rate_limiter.feature_flags._flags", {"redis_rate_limiter": value})


class TestDistributedRateLimiter:
    async def test_flag_disabled_returns_true(self, monkeypatch) -> None:
        _set_flag(monkeypatch, False)
        limiter = DistributedRateLimiter()
        assert await limiter.is_allowed("key", limit=1, window=10) is True
        assert limiter._redis is None

    async def test_import_error_returns_true(self, monkeypatch) -> None:
        _set_flag(monkeypatch, True)
        monkeypatch.setitem(sys.modules, "redis.asyncio", None)
        limiter = DistributedRateLimiter()
        assert await limiter.is_allowed("key", limit=1, window=10) is True

    async def test_redis_allowed_within_limit(self, monkeypatch) -> None:
        _set_flag(monkeypatch, True)
        client = MagicMock()
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[0, 0, 2, 0])
        client.pipeline.return_value = pipe
        monkeypatch.setattr("redis.asyncio.from_url", MagicMock(return_value=client))
        limiter = DistributedRateLimiter("redis://x")
        assert await limiter.is_allowed("key", limit=2, window=10) is True
        assert limiter._redis is client

    async def test_redis_blocked_over_limit(self, monkeypatch) -> None:
        _set_flag(monkeypatch, True)
        client = MagicMock()
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[0, 0, 3, 0])
        client.pipeline.return_value = pipe
        monkeypatch.setattr("redis.asyncio.from_url", MagicMock(return_value=client))
        limiter = DistributedRateLimiter()
        assert await limiter.is_allowed("key", limit=2, window=10) is False

    async def test_redis_empty_results(self, monkeypatch) -> None:
        _set_flag(monkeypatch, True)
        client = MagicMock()
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[0])
        client.pipeline.return_value = pipe
        monkeypatch.setattr("redis.asyncio.from_url", MagicMock(return_value=client))
        limiter = DistributedRateLimiter()
        assert await limiter.is_allowed("key", limit=5, window=10) is True

    async def test_redis_cached(self, monkeypatch) -> None:
        _set_flag(monkeypatch, True)
        client = SimpleNamespace(pipeline=MagicMock())
        limiter = DistributedRateLimiter()
        limiter._redis = client
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[0, 0, 1, 0])
        client.pipeline.return_value = pipe
        assert await limiter.is_allowed("key", limit=1, window=10) is True
