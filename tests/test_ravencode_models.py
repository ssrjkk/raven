from __future__ import annotations

from ravencode.core.models import (
    ModelConfig,
    get_context_window,
    get_max_tokens,
    get_model_config,
    register_model,
)


class TestModelRegistry:
    def test_register_and_get(self) -> None:
        cfg = ModelConfig(name="t", provider="p", max_tokens=123, context_window=456)
        register_model("t", cfg)
        assert get_model_config("t") is cfg

    def test_get_missing_returns_none(self) -> None:
        assert get_model_config("does-not-exist") is None

    def test_max_tokens_known(self) -> None:
        cfg = ModelConfig(name="t", provider="p", max_tokens=2000, context_window=10000)
        register_model("t2", cfg)
        assert get_max_tokens("t2") == 2000

    def test_max_tokens_default(self) -> None:
        assert get_max_tokens() == 4096
        assert get_max_tokens("unknown-model") == 4096

    def test_context_window_known(self) -> None:
        cfg = ModelConfig(name="t", provider="p", max_tokens=1, context_window=64000)
        register_model("t3", cfg)
        assert get_context_window("t3") == 64000

    def test_context_window_default(self) -> None:
        assert get_context_window() == 128_000
        assert get_context_window("unknown-model") == 128_000

    def test_dataclass_default_costs(self) -> None:
        cfg = ModelConfig(name="t", provider="p", max_tokens=1, context_window=2)
        assert cfg.cost_per_1k_input == 0.0
        assert cfg.cost_per_1k_output == 0.0
