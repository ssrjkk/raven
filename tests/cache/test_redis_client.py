from __future__ import annotations

import pytest

from raven.core.cache.redis_client import RedisClient

_NO_REDIS = "redis://127.0.0.1:16399/0?socket_connect_timeout=0.5"


class TestRedisClientInit:
    def test_default_parameters(self) -> None:
        c = RedisClient(url="redis://localhost:6379/0")
        assert c.url == "redis://localhost:6379/0"
        assert c.max_connections == 50
        assert c.retry_attempts == 3
        assert c.is_healthy is False

    def test_custom_parameters(self) -> None:
        c = RedisClient(url="redis://r:6379/1", max_connections=10, retry_attempts=5)
        assert c.url == "redis://r:6379/1"
        assert c.max_connections == 10
        assert c.retry_attempts == 5

    async def test_not_connected_by_default(self) -> None:
        c = RedisClient(url="redis://localhost:6379/0")
        assert c.is_healthy is False
        hc = await c.health_check()
        assert hc["status"] == "disconnected"

    async def test_ping_before_connect_returns_false(self) -> None:
        c = RedisClient(url="redis://localhost:6379/0")
        result = await c.ping()
        assert result is False


class TestRedisClientConnect:
    async def test_connect_to_nonexistent_redis_returns_false(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        result = await c.connect()
        assert result is False
        assert c.is_healthy is False
        await c.disconnect()

    async def test_double_connect_is_idempotent(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.connect()
        await c.disconnect()


class TestRedisClientExecute:
    async def test_execute_with_retry_raises_on_all_failures(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=2)
        await c.connect()
        with pytest.raises(Exception):
            await c._execute_with_retry("ping", c._client.ping)  # type: ignore[union-attr]
        await c.disconnect()

    async def test_disconnect_sets_unhealthy(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        assert c.is_healthy is False
        assert c._client is None
        assert c._pool is None


class TestRedisClientGraceful:
    async def test_health_check_after_disconnect(self) -> None:
        c = RedisClient(url=_NO_REDIS)
        await c.connect()
        await c.disconnect()
        hc = await c.health_check()
        assert hc["status"] == "disconnected"

    async def test_operations_after_connect_failure(self) -> None:
        c = RedisClient(url="redis://invalid:9999/0?socket_connect_timeout=0.5", max_connections=2, retry_attempts=1)
        await c.connect()
        assert c.is_healthy is False
        hc = await c.health_check()
        assert hc["status"] == "disconnected"
        await c.disconnect()
