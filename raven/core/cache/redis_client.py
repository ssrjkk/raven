from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any

from loguru import logger

try:
    import redis.asyncio as aioredis

    _HAS_REDIS = True
    _Redis = aioredis.Redis
    _ConnectionPool = aioredis.ConnectionPool
    _ConnectionError = aioredis.ConnectionError
except ImportError:
    _HAS_REDIS = False

    class _Redis:  # type: ignore[no-redef]
        pass

    class _ConnectionPool:  # type: ignore[no-redef]
        pass

    class _ConnectionError(ConnectionError):  # type: ignore[no-redef]
        pass


class RedisNotAvailableError(RuntimeError):
    pass


class RedisClient:
    def __init__(self, url: str, max_connections: int = 50, retry_attempts: int = 3, retry_base_delay: float = 0.5) -> None:
        self.url = url
        self.max_connections = max_connections
        self.retry_attempts = retry_attempts
        self._retry_base_delay = retry_base_delay
        self._pool: _ConnectionPool | None = None
        self._client: _Redis | None = None
        self._is_healthy = False

    @property
    def is_healthy(self) -> bool:
        return _HAS_REDIS and self._is_healthy and self._client is not None

    async def connect(self) -> bool:
        if not _HAS_REDIS:
            logger.warning("redis package not installed — RedisClient disabled")
            return False
        try:
            self._pool = _ConnectionPool.from_url(
                self.url, max_connections=self.max_connections, decode_responses=True
            )
            self._client = _Redis(connection_pool=self._pool)
            await self._client.ping()
            self._is_healthy = True
            logger.info("redis_client.connected", url=self.url)
            return True
        except _ConnectionError as e:
            logger.error("redis_client.connection_failed", error=str(e))
            self._is_healthy = False
            return False
        except Exception as e:
            logger.error("redis_client.connect_unexpected_error", error=str(e))
            self._is_healthy = False
            return False

    async def disconnect(self) -> None:
        self._is_healthy = False
        if self._pool:
            await self._pool.disconnect()
            self._pool = None
        self._client = None
        logger.info("redis_client.disconnected")

    async def _execute_with_retry(self, operation: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_error: Exception = RedisNotAvailableError("no retry attempts configured")
        for attempt in range(self.retry_attempts):
            try:
                return await func(*args, **kwargs)
            except _ConnectionError as e:
                last_error = e
                logger.warning(
                    "redis_client.retry",
                    operation=operation,
                    attempt=attempt + 1,
                    max_attempts=self.retry_attempts,
                    error=str(e),
                )
                if attempt < self.retry_attempts - 1:
                    delay = self._backoff_delay(attempt)
                    await asyncio.sleep(delay)
                    await self.connect()
        raise last_error

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._retry_base_delay * (2**attempt)
        jitter: float = random.uniform(0.5, 1.5)  # noqa: S311
        return delay * jitter  # type: ignore[no-any-return]

    async def ping(self) -> bool:
        if not self.is_healthy or self._client is None:
            return False
        try:
            return await self._client.ping()
        except _ConnectionError:
            self._is_healthy = False
            return False

    async def health_check(self) -> dict[str, Any]:
        if not self.is_healthy or self._client is None:
            return {"status": "disconnected"}
        try:
            info = await self._client.info(section="server")
            return {"status": "healthy", "redis_version": info.get("redis_version", "")}
        except _ConnectionError as e:
            self._is_healthy = False
            return {"status": "unhealthy", "error": str(e)}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def get_client(self) -> _Redis:
        if self._client is None:
            raise RedisNotAvailableError("RedisClient not connected — call connect() first")
        return self._client

    async def __aenter__(self) -> RedisClient:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.disconnect()
