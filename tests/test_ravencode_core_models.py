from __future__ import annotations

from collections.abc import Generator

import pytest

import ravencode.core.models as models_mod
from ravencode.core.models import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_TOKENS,
    ModelConfig,
    get_context_window,
    get_max_tokens,
    get_model_config,
    register_model,
)


@pytest.fixture(autouse=True)
def reset_models() -> Generator[None, None, None]:
    original = dict(models_mod._MODELS)
    models_mod._MODELS.clear()
    yield
    models_mod._MODELS.clear()
    models_mod._MODELS.update(original)


class TestModelConfig:
    def test_defaults(self) -> None:
        cfg = ModelConfig(name="m", provider="p", max_tokens=100, context_window=200)
        assert cfg.cost_per_1k_input == 0.0
        assert cfg.cost_per_1k_output == 0.0

    def test_fields(self) -> None:
        cfg = ModelConfig(name="m", provider="p", max_tokens=100, context_window=200, cost_per_1k_input=0.1, cost_per_1k_output=0.2)
        assert cfg.name == "m"
        assert cfg.provider == "p"
        assert cfg.max_tokens == 100
        assert cfg.context_window == 200
        assert cfg.cost_per_1k_input == 0.1
        assert cfg.cost_per_1k_output == 0.2


class TestModelRegistry:
    def test_register_and_get(self) -> None:
        cfg = ModelConfig(name="m", provider="p", max_tokens=100, context_window=200)
        register_model("m", cfg)
        assert get_model_config("m") is cfg

    def test_get_missing(self) -> None:
        assert get_model_config("nope") is None

    def test_get_max_tokens_known(self) -> None:
        register_model("m", ModelConfig(name="m", provider="p", max_tokens=100, context_window=200))
        assert get_max_tokens("m") == 100

    def test_get_max_tokens_unknown(self) -> None:
        assert get_max_tokens("nope") == DEFAULT_MAX_TOKENS

    def test_get_max_tokens_none(self) -> None:
        assert get_max_tokens() == DEFAULT_MAX_TOKENS

    def test_get_context_window_known(self) -> None:
        register_model("m", ModelConfig(name="m", provider="p", max_tokens=100, context_window=200))
        assert get_context_window("m") == 200

    def test_get_context_window_unknown(self) -> None:
        assert get_context_window("nope") == DEFAULT_CONTEXT_WINDOW

    def test_get_context_window_none(self) -> None:
        assert get_context_window() == DEFAULT_CONTEXT_WINDOW

    def test_overwrite(self) -> None:
        register_model("m", ModelConfig(name="m", provider="p", max_tokens=1, context_window=2))
        register_model("m", ModelConfig(name="m", provider="p", max_tokens=3, context_window=4))
        assert get_max_tokens("m") == 3
