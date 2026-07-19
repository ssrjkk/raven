from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio

from raven.core.cache.redis_client import RedisClient


@pytest.fixture(scope="session")
def redis_url() -> Generator[str, None, None]:
    try:
        from testcontainers.redis import RedisContainer
    except ImportError:
        yield "redis://localhost:16379/0?socket_connect_timeout=0.5"
        return
    try:
        with RedisContainer("redis:7-alpine") as redis:
            yield redis.get_connection_url()
    except Exception:
        yield "redis://localhost:16379/0?socket_connect_timeout=0.5"


@pytest_asyncio.fixture
async def redis_client(redis_url: str) -> AsyncGenerator[RedisClient, None]:
    client = RedisClient(url=redis_url, max_connections=5, retry_attempts=1)
    connected = await client.connect()
    if not connected:
        pytest.skip("Redis not available — start with: docker run -d -p 16379:6379 redis:7-alpine")
    try:
        yield client
    finally:
        await client.disconnect()
