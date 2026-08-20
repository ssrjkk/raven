from __future__ import annotations

import asyncio
import hashlib
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
from raven.core.instrumented import InstrumentedLLMProvider
from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.queue import PRIORITY_NORMAL, LLMQueueTimeoutError, PriorityAdmissionQueue
from raven.core.metrics import metrics
from raven.core.tracing import trace_llm_call

_HAS_TIER_CONFIG: bool | None = None


def _tiers_configured() -> bool:
    global _HAS_TIER_CONFIG
    if _HAS_TIER_CONFIG is not None:
        return _HAS_TIER_CONFIG
    _HAS_TIER_CONFIG = bool(settings.model_fast or settings.model_balanced or settings.model_quality)
    return _HAS_TIER_CONFIG


class LLMRouter:
    _CACHE_TTL = 5.0
    _CACHE_TOOL_TTL = 3.0
    _CACHE_LONG_TTL = 10.0
    _CACHE_MAXSIZE = 10000

    def __init__(self, providers_config: dict[str, Any] | None = None, llm_cache: LLMCache | None = None):
        self._providers: dict[str, LLMProvider] = {}
        self._providers_config = providers_config or {}
        self._cache: OrderedDict[str, tuple[float, float, LLMResponse]] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._admission = PriorityAdmissionQueue(settings.llm_max_concurrent, settings.llm_queue_timeout)
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

    def set_admission_concurrency(self, limit: int) -> None:
        self._admission.set_concurrency(limit)

    @property
    def admission_active(self) -> int:
        return self._admission.active

    @property
    def admission_queued(self) -> int:
        return self._admission.queued

    @staticmethod
    def _cache_key(messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None) -> str:
        normalized: list[dict[str, Any]] = []
        for m in messages:
            item = dict(m)
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                item["content"] = " ".join(m["content"].split())
            normalized.append(item)
        payload = json.dumps({"m": normalized, "t": tools}, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{model}|{digest}"

    @staticmethod
    def _ttl_for(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> float:
        if tools:
            return LLMRouter._CACHE_TOOL_TTL
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, str) and len(content) > 200:
                    return LLMRouter._CACHE_LONG_TTL
                break
        return LLMRouter._CACHE_TTL

    async def _get_cached(self, key: str) -> LLMResponse | None:
        async with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None:
                ts, ttl, resp = entry
                if (time.monotonic() - ts) < ttl:
                    self._cache.move_to_end(key)
                    return resp
                del self._cache[key]
            return None

    async def _set_cached(self, key: str, resp: LLMResponse, ttl: float) -> None:
        async with self._cache_lock:
            if len(self._cache) >= LLMRouter._CACHE_MAXSIZE:
                self._cache.popitem(last=False)
            self._cache[key] = (time.monotonic(), ttl, resp)

    def _get_provider(self, model: str) -> LLMProvider:
        if not model:
            model = settings.default_model
        if settings.ghost_mode:
            key = "ollama"
        elif model.startswith("openrouter/"):
            key = "openrouter"
        elif model.startswith(("claude", "anthropic/")):
            key = "anthropic"
        elif model.startswith("ollama/"):
            key = "ollama"
        elif model.startswith(("gpt", "o1", "o3")):
            key = "openai"
        elif model.startswith("vllm/"):
            key = "vllm"
        elif model.startswith("copilot/"):
            key = "copilot"
        elif model.startswith(("vertex/", "gemini/")):
            key = "vertex"
        elif model.startswith("bedrock/"):
            key = "bedrock"
        elif model.startswith("groq/"):
            key = "groq"
        else:
            key = "ollama"
        _requires_key = {"openai", "anthropic", "openrouter", "groq", "vertex", "bedrock", "copilot", "azure"}
        if key in _requires_key:
            from raven.core.config_discovery import get_discovered_keys

            discovery = get_discovered_keys()
            env_map = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "groq": "GROQ_API_KEY",
                "vertex": "GOOGLE_API_KEY",
                "bedrock": "AWS_ACCESS_KEY_ID",
                "copilot": "GITHUB_TOKEN",
                "azure": "AZURE_API_KEY",
            }
            env_name = env_map.get(key, "")
            if env_name and not discovery.is_available(env_name):
                raise RuntimeError(
                    f"Provider '{key}' requires {env_name} which is not set. "
                    f"Available providers: {', '.join(discovery.providers_available) or 'ollama (local)'}. "
                    f"Set the key in .env or use an available provider."
                )
        if key not in self._providers:
            from raven.core.llm.factory import LLMProviderFactory

            overrides = dict(self._providers_config.get(key, {}))
            api_key = overrides.pop("api_key", None)
            raw = LLMProviderFactory.create(key, api_key=api_key, **overrides)
            self._providers[key] = InstrumentedLLMProvider(raw, provider_name=key)
        return self._providers[key]

    def _resolve_model(self, messages: list[dict[str, Any]], model: str | None) -> str:
        if model:
            return model
        if _tiers_configured():
            from raven.core.model_tiers import select_model

            return select_model(messages)
        return settings.default_model

    # --- public entry points (admission-controlled) ---

    async def complete_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        priority: float = PRIORITY_NORMAL,
    ) -> AsyncIterator[str]:
        model = self._resolve_model(messages, model)
        try:
            await self._admission.acquire(priority)
        except LLMQueueTimeoutError as e:
            logger.warning("LLM stream request dropped: {}", e)
            metrics.inc("llm_queue_timeout", {"model": model})
            raise
        try:
            async for token in self._stream_with_failover(messages, model, tools):
                yield token
        finally:
            await self._admission.release()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        priority: float = PRIORITY_NORMAL,
    ) -> LLMResponse:
        model = self._resolve_model(messages, model)
        key = self._cache_key(messages, model, tools)
        cached = await self._get_cached(key)
        if cached is not None:
            metrics.inc("llm_cache_hit", {"model": model})
            return cached
        if self._llm_cache:
            redis_cached = await self._llm_cache.get(model, messages, tools)
            if redis_cached is not None:
                await self._set_cached(key, redis_cached, self._ttl_for(messages, tools))
                metrics.inc("llm_cache_hit", {"model": model})
                return redis_cached
        try:
            await self._admission.acquire(priority)
        except LLMQueueTimeoutError as e:
            logger.warning("LLM request dropped: {}", e)
            metrics.inc("llm_queue_timeout", {"model": model})
            raise
        try:
            return await self._complete_with_failover(messages, model, tools, key)
        finally:
            await self._admission.release()

    # --- internal: single-model attempts + failover (no admission) ---

    async def complete_unthrottled(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        model = self._resolve_model(messages, model)
        key = self._cache_key(messages, model, tools)
        cached = await self._get_cached(key)
        if cached is not None:
            return cached
        return await self._complete_model(messages, model, tools, key)

    async def complete_stream_unthrottled(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        model = self._resolve_model(messages, model)
        async for token in self._stream_model(messages, model, tools):
            yield token

    async def _complete_with_failover(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None, key: str
    ) -> LLMResponse:
        primary_exc: Exception | None = None
        try:
            return await self._complete_model(messages, model, tools, key)
        except (RuntimeError, httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
            primary_exc = e
            logger.warning("Primary model '{}' failed after retries: {}", model, e)

        logger.info("Trying failover models for request (primary: {})", model)
        try:
            failover = ModelFailover(self)
            return await failover.complete(messages, tools=tools)
        except Exception as f:
            metrics.inc("llm_request_result", {"model": model, "status": "error"})
            msg = str(primary_exc or f)
            raise RuntimeError(
                f"All LLM providers exhausted. Primary model '{model}' failed: {msg[:200]}. "
                f"Check your API keys in .env or try a different model."
            ) from f

    async def _complete_model(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None, key: str
    ) -> LLMResponse:
        primary_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                provider = self._get_provider(model)
                with trace_llm_call(model=model):
                    resp = await provider.complete(messages, model, tools)
                metrics.inc("llm_request_result", {"model": model, "status": "ok"})
                if self._llm_cache:
                    await self._llm_cache.set(model, messages, resp, tools)
                await self._set_cached(key, resp, self._ttl_for(messages, tools))
                return resp
            except (RuntimeError, httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
                primary_exc = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM call failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        settings.llm_retry_max,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning("Primary model '{}' failed after {} attempts: {}", model, settings.llm_retry_max, e)
            except Exception as e:
                primary_exc = e
                logger.warning("LLM call failed: {}", e)
                break
        raise primary_exc or RuntimeError(f"Primary model '{model}' failed")

    async def _stream_with_failover(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[str]:
        last_exc: Exception | None = None
        try:
            async for token in self._stream_model(messages, model, tools):
                yield token
            return
        except (RuntimeError, httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            logger.warning("Primary stream '{}' failed after retries: {}", model, e)

        logger.info("Stream failover for model '{}'", model)
        try:
            failover = ModelFailover(self)
            async for token in failover.complete_stream(messages, tools=tools):
                yield token
            return
        except Exception as f:
            msg = str(last_exc or f)
            raise RuntimeError(
                f"All LLM providers exhausted for streaming. Primary '{model}' failed: {msg[:200]}."
            ) from f

    async def _stream_model(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[str]:
        last_exc: Exception | None = None
        for attempt in range(max(1, settings.llm_retry_max)):
            try:
                provider = self._get_provider(model)
                metrics.inc("llm_stream_start", {"model": model, "provider": type(provider).__name__})
                with trace_llm_call(model=model):
                    async for token in provider.complete_stream(messages, model, tools):
                        yield token
                return
            except (RuntimeError, httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if attempt < settings.llm_retry_max - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        settings.llm_retry_max,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "Primary stream '{}' failed after {} attempts: {}", model, settings.llm_retry_max, e
                    )
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
        raise last_exc or RuntimeError(f"Primary stream '{model}' failed")


def _parse_retry_after(headers: Any, default: int = 5) -> int:
    from raven.core.llm.providers.base import _parse_retry_after as _parse

    return _parse(headers, default)


async def default_provider_call(messages: list[dict[str, Any]]) -> dict[str, str]:
    router = LLMRouter()
    resp = await router.complete(messages)
    return {"content": resp.content}


def get_default_provider() -> Callable[..., Any]:
    return default_provider_call
