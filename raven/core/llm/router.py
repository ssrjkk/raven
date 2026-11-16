from __future__ import annotations

import asyncio
import hashlib
import re
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
from raven.core.provider_routing import credential_fingerprint, missing_requirements, provider_for_model
from raven.core.tracing import trace_llm_call


def _tiers_configured() -> bool:
    return bool(settings.model_fast or settings.model_balanced or settings.model_quality)


class LLMRouter:
    _CACHE_TTL = 5.0
    _CACHE_TOOL_TTL = 3.0
    _CACHE_LONG_TTL = 10.0
    _CACHE_MAXSIZE = 10000

    def __init__(self, providers_config: dict[str, Any] | None = None, llm_cache: LLMCache | None = None):
        self._providers: dict[str, LLMProvider] = {}
        self._provider_fingerprints: dict[str, str] = {}
        self._retiring: set[asyncio.Task[None]] = set()
        self._providers_config = providers_config or {}
        self._cache: OrderedDict[str, tuple[float, float, LLMResponse]] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._admission = PriorityAdmissionQueue(settings.llm_max_concurrent, settings.llm_queue_timeout)
        self._llm_cache = llm_cache
        self._failover: ModelFailover | None = None

    def _get_failover(self) -> ModelFailover:
        if self._failover is None:
            self._failover = ModelFailover(self)
        return self._failover

    async def cleanup(self):
        for p in self._providers.values():
            try:
                await p.cleanup()
            except (ConnectionError, TimeoutError):
                logger.warning("LLM provider cleanup failed: connection error")
        self._providers.clear()
        self._provider_fingerprints.clear()
        if self._retiring:
            await asyncio.gather(*list(self._retiring), return_exceptions=True)
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
                item["content"] = re.sub(r"[ \t]+", " ", m["content"]).strip()
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
        key = provider_for_model(model, ghost_mode=settings.ghost_mode)
        overrides = dict(self._providers_config.get(key, {}))
        missing = missing_requirements(key, overrides)
        if missing:
            from raven.core.config_discovery import get_discovered_keys

            available = ", ".join(get_discovered_keys().providers_available) or "ollama (local)"
            raise RuntimeError(
                f"Provider '{key}' requires {' and '.join(missing)} which is not set. "
                f"Available providers: {available}. "
                f"Set the key in .env or use an available provider."
            )
        fingerprint = credential_fingerprint(key, overrides)
        cached = self._providers.get(key)
        if cached is not None and self._provider_fingerprints.get(key, fingerprint) == fingerprint:
            return cached
        if cached is not None:
            logger.info("Provider {} is rebuilt: what it was built with is no longer what is configured", key)
            del self._providers[key]
            self._retire(cached)

        from raven.core.llm.factory import LLMProviderFactory

        api_key = overrides.pop("api_key", None)
        raw = LLMProviderFactory.create(key, api_key=api_key, **overrides)
        self._providers[key] = InstrumentedLLMProvider(raw, provider_name=key)
        self._provider_fingerprints[key] = fingerprint
        return self._providers[key]

    def _retire(self, provider: LLMProvider) -> None:
        """Close the client the router just replaced.

        A provider snapshots its credential and its connection pool when it is constructed, so the
        instance being replaced is closed, not orphaned. `_get_provider` is synchronous and normally runs
        inside the caller's event loop, where a close can only be scheduled; the task is kept referenced
        and its failure logged, because an unretrieved task exception surfaces as a warning at garbage
        collection. Called from a frame with no running loop, the close simply runs here.
        """
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            asyncio.run(self._close_quietly(provider))
            return
        task = loop.create_task(self._close_quietly(provider))
        self._retiring.add(task)
        task.add_done_callback(self._retiring.discard)

    async def _close_quietly(self, provider: LLMProvider) -> None:
        try:
            await provider.cleanup()
        except Exception as exc:
            logger.warning("Retired provider cleanup failed: {}", exc)

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

    async def complete_stream_deltas(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        priority: float = PRIORITY_NORMAL,
    ) -> AsyncIterator[dict[str, Any]]:
        """Typed delta stream: token events plus tool-call fragments."""
        model = self._resolve_model(messages, model)
        try:
            await self._admission.acquire(priority)
        except LLMQueueTimeoutError as e:
            logger.warning("LLM delta stream request dropped: {}", e)
            metrics.inc("llm_queue_timeout", {"model": model})
            raise
        try:
            async for ev in self._stream_model_deltas(messages, model, tools):
                yield ev
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
            failover = self._get_failover()
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
        attempts = max(1, settings.llm_retry_max)
        for attempt in range(attempts):
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
                    if attempt >= attempts - 1:
                        logger.warning("Primary model '{}' rate limited on the final attempt: {}", model, e)
                        break
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if attempt < attempts - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM call failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        attempts,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning("Primary model '{}' failed after {} attempts: {}", model, attempts, e)
            except Exception as e:
                primary_exc = e
                logger.warning("LLM call failed: {}", e)
                break
        raise _as_runtime_error(primary_exc, f"Primary model '{model}' failed")

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
            failover = self._get_failover()
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
        yielded = False
        attempts = max(1, settings.llm_retry_max)
        for attempt in range(attempts):
            try:
                provider = self._get_provider(model)
                metrics.inc("llm_stream_start", {"model": model, "provider": type(provider).__name__})
                with trace_llm_call(model=model):
                    async for token in provider.complete_stream(messages, model, tools):
                        yielded = True
                        yield token
                return
            except (RuntimeError, httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
                if yielded:
                    # tokens already delivered: retrying would duplicate the stream mid-way
                    raise RuntimeError(f"Stream '{model}' failed after {attempt + 1} attempt(s) mid-stream") from e
                last_exc = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                    if attempt >= attempts - 1:
                        logger.warning("Primary stream '{}' rate limited on the final attempt: {}", model, e)
                        metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
                        break
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if attempt < attempts - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        attempts,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning("Primary stream '{}' failed after {} attempts: {}", model, attempts, e)
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
            except Exception as e:
                raise RuntimeError(f"Primary stream '{model}' failed: {e}") from e
        raise last_exc or RuntimeError(f"Primary stream '{model}' failed")

    async def _stream_model_deltas(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[dict[str, Any]]:
        last_exc: Exception | None = None
        yielded = False
        attempts = max(1, settings.llm_retry_max)
        for attempt in range(attempts):
            try:
                provider = self._get_provider(model)
                metrics.inc("llm_stream_start", {"model": model, "provider": type(provider).__name__})
                with trace_llm_call(model=model):
                    async for ev in provider.complete_stream_deltas(messages, model, tools):
                        yielded = True
                        yield ev
                return
            except (RuntimeError, httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError) as e:
                if yielded:
                    # deltas already delivered: retrying would duplicate the stream mid-way
                    raise RuntimeError(
                        f"Delta stream '{model}' failed after {attempt + 1} attempt(s) mid-stream"
                    ) from e
                last_exc = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                    if attempt >= attempts - 1:
                        logger.warning("Primary delta stream '{}' rate limited on the final attempt: {}", model, e)
                        metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
                        break
                    retry_after = _parse_retry_after(e.response.headers, 5)
                    logger.warning("LLM rate limited (429), retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                if attempt < attempts - 1:
                    delay = settings.llm_retry_delay * (2**attempt)
                    logger.warning(
                        "LLM delta stream failed (attempt {}/{}): {}, retrying in {}s",
                        attempt + 1,
                        attempts,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "Primary delta stream '{}' failed after {} attempts: {}",
                        model,
                        attempts,
                        e,
                    )
                    metrics.inc("llm_stream_error", {"model": model, "error": type(e).__name__})
            except Exception as e:
                raise RuntimeError(f"Primary delta stream '{model}' failed: {e}") from e

        # Deltas are unavailable on the primary provider: degrade gracefully to
        # a non-streaming answer (failover chain included) delivered as events.
        logger.info("Delta stream unavailable for '{}', falling back to non-streaming", model)
        try:
            key = self._cache_key(messages, model, tools)
            resp = await self._complete_with_failover(messages, model, tools, key)
        except Exception as f:
            msg = str(last_exc or f)
            raise RuntimeError(
                f"All LLM providers exhausted for delta streaming. Primary '{model}' failed: {msg[:200]}."
            ) from f
        if resp.tool_calls:
            for i, tc in enumerate(resp.tool_calls):
                yield {
                    "type": "tool_call",
                    "index": i,
                    "id": tc.id,
                    "name": tc.name,
                    "args_fragment": json.dumps(tc.arguments),
                }
        else:
            yield {"type": "token", "text": resp.content}


def _as_runtime_error(exc: Exception | None, fallback_msg: str) -> RuntimeError:
    if isinstance(exc, RuntimeError):
        return exc
    err = RuntimeError(f"{fallback_msg}: {exc}")
    err.__cause__ = exc
    return err


def _parse_retry_after(headers: Any, default: int = 5) -> int:
    from raven.core.llm.providers.base import _parse_retry_after as _parse

    return _parse(headers, default, cap=settings.llm_retry_after_cap)


_default_router: LLMRouter | None = None


def default_llm_router() -> LLMRouter:
    """The router the gateway, the tools and the admin console all share.

    One instance is the point: it is what caches the providers, so it is also what has to be told when
    a credential underneath them changes.
    """
    global _default_router
    if _default_router is None:
        _default_router = LLMRouter()
    return _default_router


async def default_provider_call(messages: list[dict[str, Any]]) -> dict[str, str]:
    router = default_llm_router()
    resp = await router.complete(messages)
    return {"content": resp.content}


def get_default_provider() -> Callable[..., Any]:
    return default_provider_call
