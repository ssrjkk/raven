from __future__ import annotations

import time

import pytest

from raven.core.security.rate_limiter import RateLimiter, TokenBucket


@pytest.fixture
def limiter():
    return RateLimiter(
        channel_limits={"telegram": {"rate": 100.0, "burst": 200}},
        user_limits={"default": {"rate": 50.0, "burst": 100}},
    )


@pytest.mark.asyncio
async def test_channel_rate_limit_allows_within_bounds(limiter):
    ok = await limiter.check_rate_limit("chan-1", channel_type="telegram")
    assert ok is True


@pytest.mark.asyncio
async def test_user_rate_limit_allows_within_bounds(limiter):
    ok = await limiter.check_rate_limit("chan-1", user_id="user-1", channel_type="telegram")
    assert ok is True


@pytest.mark.asyncio
async def test_channel_rate_limit_exceeded():
    limiter = RateLimiter(
        channel_limits={"default": {"rate": 0.01, "burst": 1}},
    )
    ok1 = await limiter.check_rate_limit("chan-1")
    assert ok1 is True
    ok2 = await limiter.check_rate_limit("chan-1")
    assert ok2 is False


@pytest.mark.asyncio
async def test_user_rate_limit_exceeded():
    limiter = RateLimiter(
        channel_limits={"default": {"rate": 100.0, "burst": 200}},
        user_limits={"default": {"rate": 0.01, "burst": 1}},
    )
    ok1 = await limiter.check_rate_limit("chan-1", user_id="user-1")
    assert ok1 is True
    ok2 = await limiter.check_rate_limit("chan-1", user_id="user-1")
    assert ok2 is False


@pytest.mark.asyncio
async def test_different_channels_independent(limiter):
    await limiter.check_rate_limit("chan-1", channel_type="telegram")
    ok = await limiter.check_rate_limit("chan-2", channel_type="telegram")
    assert ok is True


@pytest.mark.asyncio
async def test_clear_resets_buckets(limiter):
    await limiter.check_rate_limit("chan-1", channel_type="telegram")
    assert len(limiter._channel_buckets) == 1
    limiter.clear()
    assert len(limiter._channel_buckets) == 0
    assert len(limiter._user_buckets) == 0


def test_token_bucket_properties():
    bucket = TokenBucket(rate=4.0, burst=8)
    assert bucket.rate == 4.0
    assert bucket.burst == 8


def test_token_bucket_default_burst_derived_from_rate():
    bucket = TokenBucket(rate=3.0)
    assert bucket.burst == 6


def test_set_channel_and_user_limit(limiter):
    limiter.set_channel_limit("discord", rate=5.0, burst=10)
    assert limiter._channel_limits["discord"] == {"rate": 5.0, "burst": 10}
    limiter.set_user_limit("vip", rate=50.0, burst=100)
    assert limiter._user_limits["vip"] == {"rate": 50.0, "burst": 100}


def test_get_limit_falls_back_to_default(limiter):
    assert limiter.get_channel_limit("telegram") == {"rate": 100.0, "burst": 200}
    assert limiter.get_channel_limit("unknown") == {"rate": 10.0, "burst": 20}
    assert limiter.get_user_limit("default") == {"rate": 50.0, "burst": 100}
    assert limiter.get_user_limit("nope") == {"rate": 5.0, "burst": 10}


def test_status_reports_channels_and_users(limiter):
    limiter._get_or_create_channel_bucket("chan-1", "telegram")
    limiter._get_or_create_user_bucket("user-1")
    status = limiter.status()
    assert "chan-1" in status["channels"]
    assert status["channels"]["chan-1"]["type"] == "telegram"
    assert status["channels"]["chan-1"]["burst"] == 200
    assert "user-1" in status["users"]
    assert status["users"]["user-1"]["rate"] == 50.0


@pytest.mark.asyncio
async def test_idle_buckets_are_evicted(limiter):
    await limiter.check_rate_limit("chan-1", user_id="user-1", channel_type="telegram")
    assert limiter._channel_buckets and limiter._user_buckets
    stale = time.monotonic() - TokenBucket._IDLE_TTL - 1
    limiter._channel_buckets["chan-1"]._last_access = stale
    limiter._user_buckets["user-1"]._last_access = stale
    limiter._evict_idle()
    assert "chan-1" not in limiter._channel_buckets
    assert "chan-1" not in limiter._type_cache
    assert "user-1" not in limiter._user_buckets


@pytest.mark.asyncio
async def test_active_buckets_survive_eviction(limiter):
    await limiter.check_rate_limit("chan-keep", channel_type="telegram")
    limiter._evict_idle()
    assert "chan-keep" in limiter._channel_buckets
