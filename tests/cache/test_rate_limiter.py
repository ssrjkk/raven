from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from raven.core.cache.rate_limiter import InMemoryRateLimiter, RedisRateLimiter
from raven.core.cache.redis_client import RedisClient


class TestInMemoryRateLimiter:
    async def test_is_allowed_returns_true_for_first_request(self) -> None:
        rl = InMemoryRateLimiter()
        result = await rl.is_allowed("user:1", limit=5, window_seconds=10)
        assert result is True

    async def test_is_allowed_blocks_when_limit_exceeded(self) -> None:
        rl = InMemoryRateLimiter()
        for _ in range(5):
            await rl.is_allowed("user:1", limit=5, window_seconds=10)
        result = await rl.is_allowed("user:1", limit=5, window_seconds=10)
        assert result is False

    async def test_different_keys_do_not_interfere(self) -> None:
        rl = InMemoryRateLimiter()
        for _ in range(5):
            await rl.is_allowed("user:1", limit=5, window_seconds=10)
        result = await rl.is_allowed("user:2", limit=5, window_seconds=10)
        assert result is True

    async def test_allows_burst_within_limit(self) -> None:
        rl = InMemoryRateLimiter()
        for _ in range(3):
            result = await rl.is_allowed("user:1", limit=5, window_seconds=10)
            assert result is True

    async def test_clear_resets_all_windows(self) -> None:
        rl = InMemoryRateLimiter()
        for _ in range(5):
            await rl.is_allowed("user:1", limit=5, window_seconds=10)
        rl.clear()
        result = await rl.is_allowed("user:1", limit=5, window_seconds=10)
        assert result is True


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[RedisClient, None]:
    client = RedisClient(url="redis://localhost:16379/0", max_connections=5, retry_attempts=1)
    connected = await client.connect()
    if not connected:
        pytest.skip("Redis not available — start with: docker run -d -p 16379:6379 redis:7-alpine")
    yield client
    await client.disconnect()


class TestRedisRateLimiter:
    async def test_is_allowed_returns_true_for_first_request(self, redis_client: RedisClient) -> None:
        rl = RedisRateLimiter(redis_client, InMemoryRateLimiter())
        result = await rl.is_allowed("rl:test:1", limit=5, window_seconds=10)
        assert result is True

    async def test_blocks_when_limit_exceeded(self, redis_client: RedisClient) -> None:
        rl = RedisRateLimiter(redis_client, InMemoryRateLimiter())
        for _ in range(5):
            await rl.is_allowed("rl:test:2", limit=5, window_seconds=10)
        result = await rl.is_allowed("rl:test:2", limit=5, window_seconds=10)
        assert result is False

    async def test_different_keys_independent(self, redis_client: RedisClient) -> None:
        rl = RedisRateLimiter(redis_client, InMemoryRateLimiter())
        for _ in range(5):
            await rl.is_allowed("rl:test:3a", limit=5, window_seconds=10)
        result = await rl.is_allowed("rl:test:3b", limit=5, window_seconds=10)
        assert result is True

    async def test_allows_burst_within_limit(self, redis_client: RedisClient) -> None:
        rl = RedisRateLimiter(redis_client, InMemoryRateLimiter())
        for _ in range(3):
            result = await rl.is_allowed("rl:test:4", limit=5, window_seconds=10)
            assert result is True

    async def test_fallback_when_redis_disconnected(self) -> None:
        client = RedisClient(url="redis://localhost:16379/0", max_connections=2, retry_attempts=1)
        await client.connect()
        await client.disconnect()
        fallback = InMemoryRateLimiter()
        rl = RedisRateLimiter(client, fallback)
        result = await rl.is_allowed("rl:test:5", limit=5, window_seconds=10)
        assert result is True
        assert client.is_healthy is False
