from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from loguru import logger

from raven.core._json import json
from raven.core.cache.llm_cache import LLMCache
from raven.core.config import settings
from raven.core.failover import ModelFailover
from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.metrics import InstrumentedLLMProvider, metrics
from raven.core.tracing import trace_llm_call


class LLMRouter:
    _CACHE_TTL = 2.0
    _CACHE_MAXSIZE = 1024

    def __init__(self, providers_config: dict[str, Any] | None = None, llm_cache: LLMCache | None = None):
        self._providers: dict[str, LLMProvider] = {}
        self._providers_config = providers_config or {}
        self._cache: OrderedDict[str, tuple[float, LLMResponse]] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._rate_semaphore = asyncio.Semaphore(10)
        self._llm_cache = llm_cache

    async def cleanup(self):
        for p in self._providers.values():
            try:
                await p.cleanup()
            except (ConnectionError, TimeoutError):
                logger.warning("LLM provider cleanup failed: connection error")
        self._providers.clear()
        async with self._cache_lock:
            self._cache.clear()

    @staticmethod
    def _cache_key(messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None) -> str:
        return f"{model}|{tools}|{json.dumps(messages, sort_keys=True)}"

    async def _get_cached(self, key: str) -> LLMResponse | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry and (time.monotonic() - entry[0]) < LLMRouter._CACHE_TTL:
                self._cache.move_to_end(key)
                return entry[1]
            if entry:
                del self._cache[key]
            return None

    async def _set_cached(self, key: str, resp: LLMResponse):
        async with self._cache_lock:
            if len(self._cache) >= LLMRouter._CACHE_MAXSIZE:
                self._cache.popitem(last=False)
            self._cache[key] = (time.monotonic(), resp)

    def _get_provider(self, model: str) -> LLMProvider:
        if not model:
            model = settings.default_model
        if settings.ghost_mode:
            key = "ollama"
        elif model.startswith("openrouter/"):
            key = "openrouter"
        elif model.startswith("claude") or model.startswith("anthropic/"):
            key = "anthropic"
        elif model.startswith("ollama/"):
            key = "ollama"
        elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
            key = "openai"
        elif model.startswith("vllm/"):
            key = "vllm"
        elif model.startswith("copilot/"):
            key = "copilot"
        elif model.startswith("vertex/") or model.startswith("gemini/"):
            key = "vertex"
        elif model.startswith("bedrock/"):
            key = "bedrock"
        else:
            key = "ollama"
        if key not in self._providers:
            from raven.core.llm.factory import LLMProviderFactory
            overrides = dict(self._providers_config.get(key, {}))
            api_key = overrides.pop("api_key", None)
            raw = LLMProviderFactory.create(key, api_key=api_key, **overrides)
            self._providers[key] = InstrumentedLLMProvider(raw, provider_name=key)
        return self._providers[key]

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        model = model or settings.default_model
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                async with self._rate_semaphore:
                    provider = self._get_provider(model)
                    metrics.inc("llm_stream_start", {"model": model, "provider": type(provider).__name__})
                    with trace_llm_call(model=model):
                        async for token in provider.complete_stream(messages, model, tools):
                            yield token
                return
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                last_exc = e
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1, settings.llm_retry_max, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM stream failed after {} attempts: {}", settings.llm_retry_max, e)
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1, settings.llm_retry_max, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM stream failed after {} attempts: {}", settings.llm_retry_max, e)
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
        raise last_exc or RuntimeError("LLM stream failed")

    async def complete(
        self, messages: list[dict[str, Any]], model: str | None = None, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model = model or settings.default_model
        key = self._cache_key(messages, model, tools)
        cached = await self._get_cached(key)
        if cached is not None:
            metrics.inc("llm_cache_hit", {"model": model})
            return cached
        if self._llm_cache:
            redis_cached = await self._llm_cache.get(model, messages, tools)
            if redis_cached is not None:
                await self._set_cached(key, redis_cached)
                metrics.inc("llm_cache_hit", {"model": model})
                return redis_cached
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                async with self._rate_semaphore:
                    provider = self._get_provider(model)
                    with trace_llm_call(model=model):
                        resp = await provider.complete(messages, model, tools)
                metrics.inc("llm_complete", {"model": model, "status": "ok"})
                if self._llm_cache:
                    await self._llm_cache.set(model, messages, resp, tools)
                await self._set_cached(key, resp)
                return resp
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                last_exc = e
                metrics.inc("llm_complete", {"model": model, "status": "retry"})
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM call failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1, settings.llm_retry_max, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM call failed after {} attempts: {}", settings.llm_retry_max, e)
                    try:
                        logger.info("Failover: trying alternative models")
                        failover = ModelFailover(self)
                        return await failover.complete(messages, tools=tools)
                    except Exception as f:
                        last_exc = f
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                metrics.inc("llm_complete", {"model": model, "status": "retry"})
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM call failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1, settings.llm_retry_max, e, delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error("LLM call failed after {} attempts: {}", settings.llm_retry_max, e)
                    try:
                        logger.info("Failover: trying alternative models")
                        failover = ModelFailover(self)
                        return await failover.complete(messages, tools=tools)
                    except Exception as f:
                        last_exc = f
        metrics.inc("llm_complete", {"model": model, "status": "error"})
        raise last_exc or RuntimeError("LLM call failed")


def _parse_retry_after(headers: Any, default: int = 5) -> int:
    from raven.core.llm.providers.base import _parse_retry_after as _parse
    return _parse(headers, default)


async def default_provider_call(messages: list[dict[str, Any]]) -> dict[str, str]:
    router = LLMRouter()
    resp = await router.complete(messages)
    return {"content": resp.content}


def get_default_provider() -> Callable[..., Any]:
    return default_provider_call
