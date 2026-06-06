from __future__ import annotations

import random
from typing import Any

from loguru import logger

from raven.core.config import settings
from raven.core.llm import LLMResponse, LLMRouter
from raven.core.metrics import metrics


class ModelConfig:
    def __init__(self, provider: str, model: str, weight: float = 1.0):
        self.provider = provider
        self.model = model
        self.weight = weight


class ModelFailover:
    def __init__(self, llm: LLMRouter):
        self.llm = llm
        self._models: list[ModelConfig] = []
        self._build_models()

    def _build_models(self):
        models = []
        if settings.openrouter_api_key:
            m = settings.default_model or "openrouter/openai/gpt-4o"
            models.append(ModelConfig("openrouter", m, 1.0))
        if settings.anthropic_api_key:
            models.append(ModelConfig("anthropic", "claude-sonnet-4-20250514", 0.8))
        if settings.openai_api_key:
            models.append(ModelConfig("openai", "gpt-4o", 0.7))
        if settings.ollama_base_url:
            models.append(ModelConfig("ollama", "llama3", 0.5))
        self._models = models

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        last_error = None
        for model_cfg in self._models:
            try:
                logger.info("Failover trying model: {}/{}", model_cfg.provider, model_cfg.model)
                resp = await self.llm.complete(messages, model=model_cfg.model, tools=tools)
                if resp.content or resp.tool_calls:
                    metrics.inc("failover_success", {"provider": model_cfg.provider, "model": model_cfg.model})
                    return resp
            except Exception as e:
                last_error = e
                metrics.inc("failover_fallback", {"provider": model_cfg.provider, "model": model_cfg.model})
                logger.warning("Failover: model {}/{} failed: {}", model_cfg.provider, model_cfg.model, e)
                continue
        raise last_error or RuntimeError("All models exhausted")

    async def complete_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None):
        last_error = None
        for model_cfg in self._models:
            try:
                logger.info("Failover stream trying: {}/{}", model_cfg.provider, model_cfg.model)
                async for token in self.llm.complete_stream(messages, model=model_cfg.model, tools=tools):
                    yield token
                return
            except Exception as e:
                last_error = e
                logger.warning("Failover stream: model {}/{} failed: {}", model_cfg.provider, model_cfg.model, e)
                continue
        raise last_error or RuntimeError("All models exhausted")

    def pick_random(self) -> ModelConfig:
        if not self._models:
            raise RuntimeError("No models configured")
        weights = [m.weight for m in self._models]
        return random.choices(self._models, weights=weights, k=1)[0]
