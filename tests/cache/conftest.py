from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from raven.core.cache.redis_client import RedisClient


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[RedisClient, None]:
    client = RedisClient(url="redis://localhost:16379/0", max_connections=5, retry_attempts=1)
    connected = await client.connect()
    if not connected:
        pytest.skip("Redis not available — start with: docker run -d -p 16379:6379 redis:7-alpine")
    try:
        yield client
    finally:
        await client.disconnect()
