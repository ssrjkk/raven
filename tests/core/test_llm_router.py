from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.router import LLMRouter


class DummyProvider(LLMProvider):
    def __init__(self, content: str = "ok"):
        self._content = content
        self.cleanup_called = False

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        return LLMResponse(content=self._content)

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        for word in self._content.split():
            yield word + " "

    async def cleanup(self):
        self.cleanup_called = True


class FailProvider(LLMProvider):
    def __init__(self, error: Exception):
        self._error = error

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        raise self._error

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        yield
        raise self._error

    async def cleanup(self):
        pass


def _patch_provider(provider: LLMProvider | None = None, key: str = "ollama"):
    p = patch("raven.core.llm.factory.LLMProviderFactory.create", return_value=provider or DummyProvider())
    s = patch("raven.core.llm.router.settings.ghost_mode", False)
    m = patch("raven.core.llm.router.settings.default_model", "ollama/test")
    r = patch("raven.core.llm.router.settings.llm_retry_max", 1)
    return p, s, m, r


class TestCacheKey:
    def test_deterministic(self):
        msgs = [{"role": "user", "content": "hi"}]
        k1 = LLMRouter._cache_key(msgs, "m", None)
        k2 = LLMRouter._cache_key(msgs, "m", None)
        assert k1 == k2

    def test_different_messages(self):
        k1 = LLMRouter._cache_key([{"role": "user", "content": "a"}], "m", None)
        k2 = LLMRouter._cache_key([{"role": "user", "content": "b"}], "m", None)
        assert k1 != k2

    def test_different_models(self):
        msgs = [{"role": "user", "content": "hi"}]
        k1 = LLMRouter._cache_key(msgs, "model1", None)
        k2 = LLMRouter._cache_key(msgs, "model2", None)
        assert k1 != k2

    def test_includes_tools(self):
        msgs = [{"role": "user", "content": "hi"}]
        k1 = LLMRouter._cache_key(msgs, "m", None)
        k2 = LLMRouter._cache_key(msgs, "m", [{"type": "function", "function": {"name": "f"}}])
        assert k1 != k2


class TestCacheOps:
    async def test_set_and_get(self):
        router = LLMRouter()
        key = "k1"
        resp = LLMResponse(content="cached")
        await router._set_cached(key, resp)
        got = await router._get_cached(key)
        assert got is not None
        assert got.content == "cached"

    async def test_miss(self):
        router = LLMRouter()
        got = await router._get_cached("nonexistent")
        assert got is None

    async def test_lru_eviction(self):
        router = LLMRouter()
        for i in range(LLMRouter._CACHE_MAXSIZE + 5):
            await router._set_cached(f"key_{i}", LLMResponse(content=str(i)))
        async with router._cache_lock:
            assert len(router._cache) == LLMRouter._CACHE_MAXSIZE

    async def test_move_to_end_on_hit(self):
        router = LLMRouter()
        await router._set_cached("a", LLMResponse(content="a"))
        await router._set_cached("b", LLMResponse(content="b"))
        await router._get_cached("a")
        async with router._cache_lock:
            assert list(router._cache.keys())[-1] == "a"

    async def test_ttl_expiry(self):
        router = LLMRouter()
        await router._set_cached("expired", LLMResponse(content="old"))
        async with router._cache_lock:
            router._cache["expired"] = (0.0, LLMResponse(content="old"))
        got = await router._get_cached("expired")
        assert got is None


class TestCleanup:
    async def test_cleanup_calls_provider_cleanup(self):
        router = LLMRouter()
        p = DummyProvider()
        router._providers["test"] = p
        await router.cleanup()
        assert p.cleanup_called
        assert len(router._providers) == 0
        assert len(router._cache) == 0

    async def test_cleanup_handles_error(self):
        router = LLMRouter()
        router._providers["fail"] = FailProvider(ConnectionError("boom"))
        await router.cleanup()
        assert len(router._providers) == 0


class TestGetProvider:
    def test_caches_providers(self):
        router = LLMRouter()
        dummy = DummyProvider()
        router._providers["ollama"] = dummy
        got = router._get_provider("ollama/test")
        assert got is dummy

    def test_provider_key_selection(self):
        with patch("raven.core.llm.router.settings") as mock_settings, \
             patch("raven.core.config_discovery.get_discovered_keys") as mock_disc:
            mock_settings.ghost_mode = False
            mock_settings.default_model = "ollama/test"
            mock_disc.return_value.is_available.return_value = True
            mock_disc.return_value.providers_available = ["openai", "anthropic", "openrouter", "ollama"]
            router = LLMRouter()
            all_keys = ["openrouter", "anthropic", "ollama", "openai", "vllm", "copilot", "vertex", "bedrock", "groq"]
            for k in all_keys:
                router._providers[k] = DummyProvider()
            cases = {
                "openrouter/claude": "openrouter",
                "claude-3": "anthropic",
                "anthropic/claude-3": "anthropic",
                "ollama/llama": "ollama",
                "gpt-4": "openai",
                "o1-mini": "openai",
                "vllm/model": "vllm",
                "copilot/chat": "copilot",
                "vertex/model": "vertex",
                "gemini/pro": "vertex",
                "bedrock/model": "bedrock",
                "groq/mixtral": "groq",
                "unknown_model": "ollama",
            }
            for model, expected_key in cases.items():
                got = router._get_provider(model)
                assert got is router._providers[expected_key], f"model={model}, expected key={expected_key}"

    def test_rejects_missing_key_for_required_provider(self):
        router = LLMRouter()
        with patch("raven.core.config_discovery.get_discovered_keys") as mock_disc:
            mock_disc.return_value.is_available.return_value = False
            mock_disc.return_value.providers_available = []
            with pytest.raises(RuntimeError, match="requires"):
                router._get_provider("gpt-4")


class TestComplete:
    async def test_returns_response(self):
        router = LLMRouter()
        router._providers["ollama"] = DummyProvider("hello")
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 1
            resp = await router.complete([{"role": "user", "content": "hi"}], model="ollama/test")
        assert resp.content == "hello"

    async def test_cache_hit(self):
        router = LLMRouter()
        key = LLMRouter._cache_key([{"role": "user", "content": "hi"}], "ollama/test", None)
        await router._set_cached(key, LLMResponse(content="cached"))
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 1
            resp = await router.complete([{"role": "user", "content": "hi"}], model="ollama/test")
        assert resp.content == "cached"

    async def test_retries_on_failure(self):
        call_count = 0

        class FlakyProvider(LLMProvider):
            async def complete(self, messages, model, tools=None):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise RuntimeError("transient")
                return LLMResponse(content="ok")

            async def complete_stream(self, messages, model, tools=None):
                if False:
                    yield ""

            async def cleanup(self):
                pass

        router = LLMRouter()
        router._providers["ollama"] = FlakyProvider()
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 3
            mock_settings.llm_retry_delay = 0
            resp = await router.complete([{"role": "user", "content": "hi"}], model="ollama/test")
        assert resp.content == "ok"
        assert call_count == 3

    async def test_429_retry_after(self):
        call_count = 0

        class RateLimitedProvider(LLMProvider):
            async def complete(self, messages, model, tools=None):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    resp = MagicMock(spec=httpx.Response)
                    resp.status_code = 429
                    resp.headers = {"Retry-After": "0"}
                    raise httpx.HTTPStatusError("rate limited", request=MagicMock(), response=resp)
                return LLMResponse(content="ok")

            async def complete_stream(self, messages, model, tools=None):
                if False:
                    yield ""

            async def cleanup(self):
                pass

        router = LLMRouter()
        router._providers["ollama"] = RateLimitedProvider()
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 2
            mock_settings.llm_retry_delay = 0
            resp = await router.complete([{"role": "user", "content": "hi"}], model="ollama/test")
        assert resp.content == "ok"

    async def test_exhausted_raises(self):
        router = LLMRouter()
        router._providers["ollama"] = FailProvider(RuntimeError("down"))
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 1
            mock_settings.llm_retry_delay = 0
            with patch("raven.core.failover.ModelFailover") as MockFailover:
                MockFailover.return_value.complete = AsyncMock(side_effect=RuntimeError("all fail"))
                with pytest.raises(RuntimeError, match="All LLM providers exhausted"):
                    await router.complete([{"role": "user", "content": "hi"}], model="ollama/test")


class TestCompleteStream:
    async def test_yields_tokens(self):
        router = LLMRouter()
        router._providers["ollama"] = DummyProvider("hello world")
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 1
            tokens = []
            async for tok in router.complete_stream([{"role": "user", "content": "hi"}], model="ollama/test"):
                tokens.append(tok)
        assert "".join(tokens).strip() == "hello world"

    async def test_stream_exhausted_raises(self):
        router = LLMRouter()
        router._providers["ollama"] = FailProvider(RuntimeError("boom"))
        with patch("raven.core.llm.router.settings") as mock_settings:
            mock_settings.llm_retry_max = 1
            mock_settings.llm_retry_delay = 0
            with patch("raven.core.failover.ModelFailover") as MockFailover:

                async def fail_stream(*a, **kw):
                    raise RuntimeError("all fail")
                    yield

                MockFailover.return_value.complete_stream = fail_stream
                with pytest.raises(RuntimeError, match="All LLM providers exhausted"):
                    async for _ in router.complete_stream(
                        [{"role": "user", "content": "hi"}], model="ollama/test"
                    ):
                        pass


class TestGetDefaultProvider:
    def test_get_default_provider(self):
        from raven.core.llm.router import get_default_provider

        fn = get_default_provider()
        assert callable(fn)
