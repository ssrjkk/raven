from __future__ import annotations

import pytest

from raven.core.security.rate_limiter import RateLimiter


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
