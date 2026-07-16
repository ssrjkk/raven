from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelConfig:
    name: str
    provider: str
    max_tokens: int
    context_window: int
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


DEFAULT_MAX_TOKENS = 4096
DEFAULT_CONTEXT_WINDOW = 128_000

_MODELS: dict[str, ModelConfig] = {}


def register_model(name: str, config: ModelConfig) -> None:
    _MODELS[name] = config


def get_model_config(name: str) -> ModelConfig | None:
    return _MODELS.get(name)


def get_max_tokens(name: str | None = None) -> int:
    if name and name in _MODELS:
        return _MODELS[name].max_tokens
    return DEFAULT_MAX_TOKENS


def get_context_window(name: str | None = None) -> int:
    if name and name in _MODELS:
        return _MODELS[name].context_window
    return DEFAULT_CONTEXT_WINDOW
