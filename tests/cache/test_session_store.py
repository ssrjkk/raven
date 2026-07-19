from __future__ import annotations

from datetime import UTC, datetime

import pytest

from raven.core.cache.redis_client import RedisClient
from raven.core.cache.session_store import SessionStore
from raven.core.models import Session

_NO_REDIS = "redis://localhost:16379/0?socket_connect_timeout=0.5"


class TestSessionStoreInit:
    async def test_returns_none_when_redis_disconnected(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        store = SessionStore(c)
        result = await store.get("session:nonexistent")
        assert result is None

    async def test_exists_returns_false_when_disconnected(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        store = SessionStore(c)
        assert await store.exists("session:nonexistent") is False

    async def test_delete_returns_false_when_disconnected(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        store = SessionStore(c)
        assert await store.delete("session:nonexistent") is False


class TestSessionStoreWithRedis:
    async def test_set_and_get(self, redis_client: RedisClient) -> None:
        store = SessionStore(redis_client, ttl=3600)
        session = Session(id="test:1", channel="webchat", user_id="user:1")
        await store.set(session)
        retrieved = await store.get("test:1")
        assert retrieved is not None
        assert retrieved.id == "test:1"
        assert retrieved.channel == "webchat"
        assert retrieved.user_id == "user:1"

    async def test_exists_returns_true_after_set(self, redis_client: RedisClient) -> None:
        store = SessionStore(redis_client, ttl=3600)
        session = Session(id="test:2", channel="telegram", user_id="user:2")
        await store.set(session)
        assert await store.exists("test:2") is True

    async def test_delete_removes_session(self, redis_client: RedisClient) -> None:
        store = SessionStore(redis_client, ttl=3600)
        session = Session(id="test:3", channel="discord", user_id="user:3")
        await store.set(session)
        assert await store.exists("test:3") is True
        deleted = await store.delete("test:3")
        assert deleted is True
        assert await store.exists("test:3") is False

    async def test_update_partial_fields(self, redis_client: RedisClient) -> None:
        store = SessionStore(redis_client, ttl=3600)
        session = Session(id="test:4", channel="webchat", user_id="user:4")
        await store.set(session)
        await store.update("test:4", system_prompt="be helpful")
        retrieved = await store.get("test:4")
        assert retrieved is not None
        assert retrieved.system_prompt == "be helpful"
        assert retrieved.channel == "webchat"

    async def test_get_nonexistent_returns_none(self, redis_client: RedisClient) -> None:
        store = SessionStore(redis_client, ttl=3600)
        result = await store.get("session:nonexistent")
        assert result is None
