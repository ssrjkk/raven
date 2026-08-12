from __future__ import annotations

import random
from typing import Any

from loguru import logger

from raven.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from raven.core.config_discovery import auto_model_list, get_discovered_keys
from raven.core.llm.protocol import LLMClientProtocol, LLMResponse
from raven.core.metrics import metrics


class ModelConfig:
    def __init__(self, provider: str, model: str, weight: float = 1.0):
        self.provider = provider
        self.model = model
        self.weight = weight


class ModelFailover:
    def __init__(self, llm: LLMClientProtocol):
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
        discovery = get_discovered_keys()
        available = set(discovery.providers_available)
        pool = auto_model_list()

        weights = {"ollama": 1.0, "groq": 0.9, "openrouter": 0.8, "anthropic": 0.7, "openai": 0.6, "vllm": 0.5}
        for full_model in pool:
            provider = full_model.split("/")[0] if "/" in full_model else "openai"
            if provider not in available and provider != "ollama":
                continue
            weight = weights.get(provider, 0.5)
            models.append(ModelConfig(provider, full_model, weight))

        if not models:
            models.append(ModelConfig("ollama", "llama3", 1.0))
        self._models = models

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        last_error: Exception | None = None
        for model_cfg in self._models:
            cb = self._get_circuit(model_cfg.provider)
            try:
                if not await cb.try_acquire():
                    logger.info("Circuit open, skipping {}", model_cfg.model)
                    last_error = CircuitBreakerOpenError(cb.name)
                    continue

                logger.info("Failover trying model: {}", model_cfg.model)
                complete_fn = getattr(self.llm, "complete_unthrottled", self.llm.complete)
                resp = await cb.call(complete_fn, messages, model=model_cfg.model, tools=tools)
                if resp.content or resp.tool_calls:
                    metrics.inc("failover_success", {"provider": model_cfg.provider, "model": model_cfg.model})
                    return resp  # type: ignore[no-any-return]
                logger.warning(
                    "Failover: model {} returned empty response, trying next", model_cfg.model
                )
            except CircuitBreakerOpenError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                metrics.inc("failover_fallback", {"provider": model_cfg.provider, "model": model_cfg.model})
                logger.warning("Failover: model {} failed: {}", model_cfg.model, e)
                continue
        raise last_error or RuntimeError("All models exhausted")

    async def complete_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None):
        last_error: Exception | None = None
        for model_cfg in self._models:
            cb = self._get_circuit(model_cfg.provider)
            try:
                if not await cb.try_acquire():
                    logger.info("Circuit open, skipping {} stream", model_cfg.model)
                    last_error = CircuitBreakerOpenError(cb.name)
                    continue

                logger.info("Failover stream trying: {}", model_cfg.model)

                try:
                    stream_fn = getattr(self.llm, "complete_stream_unthrottled", self.llm.complete_stream)
                    async for token in stream_fn(messages, model=model_cfg.model, tools=tools):
                        yield token
                except Exception:
                    await cb.on_failure()
                    raise

                await cb.on_success()
                return

            except CircuitBreakerOpenError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                logger.warning("Failover stream: model {} failed: {}", model_cfg.model, e)
                continue
        raise last_error or RuntimeError("All models exhausted")

    def pick_random(self) -> ModelConfig:
        if not self._models:
            raise RuntimeError("No models configured")
        weights = [m.weight for m in self._models]
        return random.choices(self._models, weights=weights, k=1)[0]
