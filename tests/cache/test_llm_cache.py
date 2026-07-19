from __future__ import annotations

import hashlib
import json

import pytest

from raven.core.cache.llm_cache import LLMCache
from raven.core.cache.redis_client import RedisClient
from raven.core.llm.protocol import LLMResponse

_NO_REDIS = "redis://localhost:16379/0?socket_connect_timeout=0.5"


class TestLLMCacheInit:
    async def test_get_returns_none_when_redis_disconnected(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        cache = LLMCache(c, ttl=300)
        result = await cache.get("gpt-4", [{"role": "user", "content": "hi"}])
        assert result is None

    async def test_set_returns_false_when_disconnected(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        cache = LLMCache(c, ttl=300)
        ok = await cache.set("gpt-4", [{"role": "user", "content": "hi"}], LLMResponse(content="hello"))
        assert ok is False

    async def test_invalidate_returns_zero_when_disconnected(self) -> None:
        c = RedisClient(url=_NO_REDIS, max_connections=2, retry_attempts=1)
        await c.connect()
        await c.disconnect()
        cache = LLMCache(c, ttl=300)
        deleted = await cache.invalidate("gpt-4")
        assert deleted == 0


class TestLLMCacheKey:
    def test_same_inputs_produce_same_key(self) -> None:
        msgs = [{"role": "user", "content": "hello"}]
        k1 = LLMCache._build_key("gpt-4", msgs)
        k2 = LLMCache._build_key("gpt-4", msgs)
        assert k1 == k2
        assert k1.startswith("llm_cache:gpt-4:")

    def test_different_inputs_produce_different_keys(self) -> None:
        k1 = LLMCache._build_key("gpt-4", [{"role": "user", "content": "hello"}])
        k2 = LLMCache._build_key("gpt-4", [{"role": "user", "content": "world"}])
        assert k1 != k2

    def test_different_models_produce_different_keys(self) -> None:
        k1 = LLMCache._build_key("gpt-4", [{"role": "user", "content": "hello"}])
        k2 = LLMCache._build_key("claude-3", [{"role": "user", "content": "hello"}])
        assert k1 != k2

    def test_key_is_deterministic(self) -> None:
        msgs = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
        k = LLMCache._build_key("gpt-4", msgs)
        digest = hashlib.sha256(json.dumps({"messages": msgs, "tools": None}, sort_keys=True, default=str).encode()).hexdigest()
        assert k == f"llm_cache:gpt-4:{digest}"


class TestLLMCacheWithRedis:
    async def test_set_and_get(self, redis_client: RedisClient) -> None:
        cache = LLMCache(redis_client, ttl=3600)
        msgs = [{"role": "user", "content": "ping"}]
        ok = await cache.set("gpt-4", msgs, LLMResponse(content="pong", finish_reason="stop"))
        assert ok is True
        result = await cache.get("gpt-4", msgs)
        assert result is not None
        assert result.content == "pong"
        assert result.finish_reason == "stop"

    async def test_cache_miss_returns_none(self, redis_client: RedisClient) -> None:
        cache = LLMCache(redis_client, ttl=3600)
        result = await cache.get("gpt-4", [{"role": "user", "content": "never_cached"}])
        assert result is None

    async def test_invalidate_clears_model_cache(self, redis_client: RedisClient) -> None:
        cache = LLMCache(redis_client, ttl=3600)
        msgs = [{"role": "user", "content": "data"}]
        await cache.set("gpt-4", msgs, LLMResponse(content="stored"))
        hit = await cache.get("gpt-4", msgs)
        assert hit is not None
        deleted = await cache.invalidate("gpt-4")
        assert deleted >= 1
        miss = await cache.get("gpt-4", msgs)
        assert miss is None

    async def test_different_tools_produce_different_keys(self, redis_client: RedisClient) -> None:
        cache = LLMCache(redis_client, ttl=3600)
        msgs = [{"role": "user", "content": "hi"}]
        tools = [{"name": "search", "parameters": {"q": "str"}}]
        ok = await cache.set("gpt-4", msgs, LLMResponse(content="a"), tools=tools)
        assert ok is True
        result_with_tools = await cache.get("gpt-4", msgs, tools=tools)
        assert result_with_tools is not None
        result_without_tools = await cache.get("gpt-4", msgs)
        assert result_without_tools is None
