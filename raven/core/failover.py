from __future__ import annotations

import random
import time
from typing import Any

from loguru import logger

from raven.core.config import settings
from raven.core.llm import LLMResponse, LLMRouter
from raven.core.metrics import metrics
from services.observability_sdk.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
)


class ModelConfig:
    def __init__(self, provider: str, model: str, weight: float = 1.0):
        self.provider = provider
        self.model = model
        self.weight = weight


class ModelFailover:
    def __init__(self, llm: LLMRouter):
        self.llm = llm
        self._models: list[ModelConfig] = []
        self._circuits: dict[str, CircuitBreaker] = {}
        self._build_models()

    def _get_circuit(self, provider: str) -> CircuitBreaker:
        if provider not in self._circuits:
            self._circuits[provider] = CircuitBreaker(
                name=provider,
                failure_threshold=3,
                recovery_timeout=30.0,
            )
        return self._circuits[provider]

    def _build_models(self):
        models = []
        if settings.ollama_base_url:
            models.append(ModelConfig("ollama", "qwen3:8b", 1.0))
            models.append(ModelConfig("ollama", "llama3", 0.9))
            models.append(ModelConfig("ollama", "mistral", 0.8))
        if settings.vllm_base_url:
            models.append(ModelConfig("vllm", "qwen3-8b", 0.7))
        if settings.openrouter_api_key:
            m = settings.default_model or "openrouter/openai/gpt-4o-mini"
            models.append(ModelConfig("openrouter", m, 0.6))
        if settings.anthropic_api_key:
            models.append(ModelConfig("anthropic", "claude-sonnet-4-20250514", 0.5))
        if settings.openai_api_key:
            models.append(ModelConfig("openai", "gpt-4o", 0.4))
        self._models = models

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        last_error: Exception | None = None
        for model_cfg in self._models:
            cb = self._get_circuit(model_cfg.provider)
            try:
                if cb.is_open:
                    logger.info("Circuit open, skipping {}/{}", model_cfg.provider, model_cfg.model)
                    last_error = CircuitBreakerOpenError(cb.name)
                    continue

                logger.info("Failover trying model: {}/{}", model_cfg.provider, model_cfg.model)
                resp = await cb.call(self.llm.complete, messages, model=model_cfg.model, tools=tools)
                if resp.content or resp.tool_calls:
                    metrics.inc("failover_success", {"provider": model_cfg.provider, "model": model_cfg.model})
                    return resp  # type: ignore[no-any-return]
                logger.warning("Failover: model {}/{} returned empty response, trying next", model_cfg.provider, model_cfg.model)
            except CircuitBreakerOpenError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                metrics.inc("failover_fallback", {"provider": model_cfg.provider, "model": model_cfg.model})
                logger.warning("Failover: model {}/{} failed: {}", model_cfg.provider, model_cfg.model, e)
                continue
        raise last_error or RuntimeError("All models exhausted")

    async def complete_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ):
        last_error: Exception | None = None
        for model_cfg in self._models:
            cb = self._get_circuit(model_cfg.provider)
            try:
                if cb.is_open:
                    logger.info("Circuit open, skipping {}/{} stream", model_cfg.provider, model_cfg.model)
                    last_error = CircuitBreakerOpenError(cb.name)
                    continue

                logger.info("Failover stream trying: {}/{}", model_cfg.provider, model_cfg.model)

                async with cb._lock:
                    if cb._state == CircuitBreakerState.OPEN:
                        cb._state = CircuitBreakerState.HALF_OPEN
                        cb._half_open_attempts = 0
                        cb._metrics["transitions"] += 1
                        logger.info("[cb/{}] half-open", cb.name)

                try:
                    async for token in self.llm.complete_stream(messages, model=model_cfg.model, tools=tools):
                        yield token
                except Exception:
                    async with cb._lock:
                        cb._failure_count += 1
                        cb._last_failure_time = time.monotonic()
                        cb._metrics["failures"] += 1
                        if cb._state == CircuitBreakerState.HALF_OPEN:
                            cb._state = CircuitBreakerState.OPEN
                            cb._metrics["transitions"] += 1
                            logger.warning("[cb/{}] open after half-open stream failure", cb.name)
                        elif cb._failure_count >= cb._failure_threshold:
                            cb._state = CircuitBreakerState.OPEN
                            cb._metrics["transitions"] += 1
                            logger.warning("[cb/{}] open after {} stream failures", cb.name, cb._failure_threshold)
                    raise

                async with cb._lock:
                    cb._metrics["successes"] += 1
                    if cb._state == CircuitBreakerState.HALF_OPEN:
                        cb._state = CircuitBreakerState.CLOSED
                        cb._failure_count = 0
                        cb._metrics["transitions"] += 1
                        logger.info("[cb/{}] closed after stream success", cb.name)
                return

            except CircuitBreakerOpenError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                logger.warning("Failover stream: model {}/{} failed: {}", model_cfg.provider, model_cfg.model, e)
                continue
        raise last_error or RuntimeError("All models exhausted")

    def pick_random(self) -> ModelConfig:
        if not self._models:
            raise RuntimeError("No models configured")
        weights = [m.weight for m in self._models]
        return random.choices(self._models, weights=weights, k=1)[0]  # noqa: S311
