from __future__ import annotations

from enum import StrEnum
from typing import Any

from loguru import logger

from raven.core.config import settings


class ModelTier(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"


TIER_MODELS: dict[str, dict[str, str]] = {
    "ollama": {
        ModelTier.FAST: "ollama/llama3.2:3b",
        ModelTier.BALANCED: "ollama/qwen2.5:7b",
        ModelTier.QUALITY: "ollama/qwen2.5:32b",
    },
    "openrouter": {
        ModelTier.FAST: "openrouter/google/gemini-2.0-flash-001",
        ModelTier.BALANCED: "openrouter/anthropic/claude-3.5-haiku",
        ModelTier.QUALITY: "openrouter/anthropic/claude-3.5-sonnet",
    },
    "openai": {
        ModelTier.FAST: "gpt-4o-mini",
        ModelTier.BALANCED: "gpt-4o",
        ModelTier.QUALITY: "gpt-4o",
    },
    "anthropic": {
        ModelTier.FAST: "claude-3-5-haiku-latest",
        ModelTier.BALANCED: "claude-3-5-sonnet-latest",
        ModelTier.QUALITY: "claude-3-5-sonnet-latest",
    },
}


def _detect_provider_family() -> str:
    model = settings.default_model
    if settings.ghost_mode:
        return "ollama"
    if model.startswith(("openrouter/",)):
        return "openrouter"
    if model.startswith(("claude", "anthropic/")):
        return "anthropic"
    if model.startswith(("gpt", "o1", "o3")):
        return "openai"
    return "ollama"


def _estimate_complexity(messages: list[dict[str, Any]]) -> str:
    total_chars = sum(len(m.get("content", "")) for m in messages)
    total_messages = len(messages)
    has_code = any("```" in m.get("content", "") or "`" in m.get("content", "") for m in messages)
    last_content = messages[-1].get("content", "") if messages else ""

    code_keywords = ["implement", "write", "code", "function", "class", "debug", "refactor", "optimize"]
    simple_keywords = ["hello", "hi", "thanks", "yes", "no", "ok", "what", "who", "when", "where"]

    code_score = sum(1 for kw in code_keywords if kw in last_content.lower())
    simple_score = sum(1 for kw in simple_keywords if last_content.lower().strip().startswith(kw))

    if total_chars < 200 and total_messages <= 2 and code_score == 0 and (simple_score > 0 or not last_content):
        return "simple"
    if total_chars > 2000 or has_code or code_score >= 1 or total_messages > 10:
        return "complex"
    return "medium"


def _resolve_default_model(tier: ModelTier | str) -> str:
    tier_obj = tier if isinstance(tier, ModelTier) else ModelTier(tier) if isinstance(tier, str) else ModelTier.BALANCED
    config_map = {
        ModelTier.FAST: settings.model_fast,
        ModelTier.BALANCED: settings.model_balanced,
        ModelTier.QUALITY: settings.model_quality,
    }
    if config_map.get(tier_obj):
        return config_map[tier_obj]
    family = _detect_provider_family()
    mapping = TIER_MODELS.get(family, TIER_MODELS["ollama"])
    return mapping.get(tier_obj.value, settings.default_model)


def select_model(messages: list[dict[str, Any]], prefer_tier: str | None = None) -> str:
    if prefer_tier:
        model = _resolve_default_model(prefer_tier)
        logger.debug("[tiers] explicit tier '{}' → model '{}'", prefer_tier, model)
        return model

    complexity = _estimate_complexity(messages)
    tier_map = {"simple": ModelTier.FAST, "medium": ModelTier.BALANCED, "complex": ModelTier.QUALITY}
    tier = tier_map.get(complexity, ModelTier.BALANCED)
    model = _resolve_default_model(tier)

    dream_override = _get_dream_tier_override(messages)
    if dream_override:
        logger.debug("[tiers] dream override → model '{}'", dream_override)
        return dream_override

    logger.debug("[tiers] complexity={} → tier={} → model='{}'", complexity, tier, model)
    return model


def _get_dream_tier_override(messages: list[dict[str, Any]]) -> str | None:
    if not messages:
        return None
    last = messages[-1].get("content", "")
    if last.startswith("/dream") or "[dream]" in last:
        return _resolve_default_model(ModelTier.FAST)
    return None


def format_tier_config(provider: str) -> dict[str, str]:
    mapping = TIER_MODELS.get(provider, TIER_MODELS["ollama"])
    return {tier.value: mapping.get(tier, "") for tier in ModelTier}
