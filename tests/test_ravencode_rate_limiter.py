from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ravencode.core.rate_limiter import DistributedRateLimiter, TokenBucket


class TestTokenBucket:
    def test_initial_burst_allows_burst_requests(self) -> None:
        bucket = TokenBucket(rate=1.0, burst=5)
        allowed = sum(1 for _ in range(5) if bucket.acquire())
        assert allowed == 5

    def test_exhausts_burst_then_denies(self) -> None:
        bucket = TokenBucket(rate=1.0, burst=2)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False

    def test_refills_over_time(self) -> None:
        bucket = TokenBucket(rate=10.0, burst=1)
        assert bucket.acquire() is True
        assert bucket.acquire() is False
        bucket._last -= 0.2
        assert bucket.acquire() is True

    def test_zero_rate_never_refills(self) -> None:
        bucket = TokenBucket(rate=0.0, burst=1)
        assert bucket.acquire() is True
        assert bucket.acquire() is False


class TestDistributedRateLimiter:
    async def test_flag_disabled_allows_all(self) -> None:
        limiter = DistributedRateLimiter()
        assert await limiter.is_allowed("key", 5, 60) is True

    async def test_ensure_redis_import_error_returns_none(self, monkeypatch) -> None:
        original_import = __import__

        def fake_import(name: str, *args, **kwargs):
            if name.startswith("redis"):
                raise ImportError("no redis")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        limiter = DistributedRateLimiter("redis://localhost:6379/0")
        redis = await limiter._ensure_redis()
        assert redis is None
        assert limiter._redis is None

    async def test_redis_allows_under_limit(self, monkeypatch) -> None:
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[1, 1, 2, 1])
        fake_redis = MagicMock()
        fake_redis.pipeline.return_value = pipe
        monkeypatch.setattr("ravencode.core.rate_limiter.feature_flags.is_enabled", lambda *a, **k: True)
        limiter = DistributedRateLimiter("redis://localhost:6379/0")
        monkeypatch.setattr(limiter, "_ensure_redis", AsyncMock(return_value=fake_redis))
        result = await limiter.is_allowed("key", 5, 60)
        assert result is True

    async def test_redis_denies_over_limit(self, monkeypatch) -> None:
        pipe = MagicMock()
        pipe.execute = AsyncMock(return_value=[1, 1, 9, 1])
        fake_redis = MagicMock()
        fake_redis.pipeline.return_value = pipe
        monkeypatch.setattr("ravencode.core.rate_limiter.feature_flags.is_enabled", lambda *a, **k: True)
        limiter = DistributedRateLimiter()
        monkeypatch.setattr(limiter, "_ensure_redis", AsyncMock(return_value=fake_redis))
        result = await limiter.is_allowed("key", 5, 60)
        assert result is False

    async def test_redis_none_allows(self, monkeypatch) -> None:
        monkeypatch.setattr("ravencode.core.rate_limiter.feature_flags.is_enabled", lambda *a, **k: True)
        limiter = DistributedRateLimiter()
        monkeypatch.setattr(limiter, "_ensure_redis", AsyncMock(return_value=None))
        result = await limiter.is_allowed("key", 5, 60)
        assert result is True
