from __future__ import annotations

from raven.core.model_tiers import ModelTier, _estimate_complexity, _resolve_default_model


class TestEstimateComplexity:
    def test_simple_short_greeting(self):
        messages = [{"role": "user", "content": "hello"}]
        assert _estimate_complexity(messages) == "simple"

    def test_simple_short_question(self):
        messages = [{"role": "user", "content": "what is python"}]
        assert _estimate_complexity(messages) == "simple"

    def test_medium_general_question(self):
        messages = [{"role": "user", "content": "explain how async await works in python in detail"}]
        assert _estimate_complexity(messages) == "medium"

    def test_medium_multiple_messages(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "what is a decorator"},
        ]
        assert _estimate_complexity(messages) == "medium"

    def test_complex_code_request(self):
        messages = [
            {
                "role": "user",
                "content": "implement a binary search tree in python with insert, delete, and search methods",
            }
        ]
        assert _estimate_complexity(messages) == "complex"

    def test_complex_with_code_block(self):
        messages = [{"role": "user", "content": "review this code:\n```python\ndef foo():\n    pass\n```"}]
        assert _estimate_complexity(messages) == "complex"

    def test_complex_many_messages(self):
        messages = [{"role": "user", "content": str(i)} for i in range(12)]
        assert _estimate_complexity(messages) == "complex"

    def test_complex_long_text(self):
        messages = [{"role": "user", "content": "x" * 2500}]
        assert _estimate_complexity(messages) == "complex"

    def test_complex_debug_keyword(self):
        messages = [{"role": "user", "content": "debug this error in my production code"}]
        assert _estimate_complexity(messages) == "complex"

    def test_empty_messages(self):
        assert _estimate_complexity([]) == "simple"


class TestModelTierEnum:
    def test_values(self):
        assert ModelTier.FAST.value == "fast"
        assert ModelTier.BALANCED.value == "balanced"
        assert ModelTier.QUALITY.value == "quality"

    def test_all_tiers_covered(self):
        assert len(ModelTier) == 3


class TestTierResolutionFollowsTheRoutingRule:
    """A tier is a *within-provider* choice: an install that bills Groq, Azure or its own adapter must
    keep the model it configured instead of being handed Ollama ids it cannot call."""

    def _resolve(self, monkeypatch, default_model: str, tier: ModelTier, *, ghost: bool = False) -> str:
        from raven.core.config import settings

        for attr in ("model_fast", "model_balanced", "model_quality"):
            monkeypatch.setattr(settings, attr, "")
        monkeypatch.setattr(settings, "default_model", default_model)
        monkeypatch.setattr(settings, "ghost_mode", ghost)
        return _resolve_default_model(tier)

    def test_a_groq_install_keeps_its_own_models(self, monkeypatch):
        for tier in ModelTier:
            assert self._resolve(monkeypatch, "groq/openai/gpt-oss-120b", tier) == "groq/openai/gpt-oss-120b"

    def test_an_azure_install_keeps_its_own_models(self, monkeypatch):
        assert self._resolve(monkeypatch, "azure/gpt-4o", ModelTier.QUALITY) == "azure/gpt-4o"

    def test_a_local_adapter_install_is_not_handed_ollama_ids(self, monkeypatch):
        assert self._resolve(monkeypatch, "local/unsloth/Qwen2.5-7B", ModelTier.FAST) == "local/unsloth/Qwen2.5-7B"

    def test_an_ollama_install_gets_the_local_tier_ladder(self, monkeypatch):
        assert self._resolve(monkeypatch, "ollama/qwen2.5:7b", ModelTier.FAST) == "ollama/llama3.2:3b"

    def test_an_openrouter_install_gets_the_openrouter_ladder(self, monkeypatch):
        assert self._resolve(monkeypatch, "openrouter/anthropic/claude-3.5-sonnet", ModelTier.FAST).startswith(
            "openrouter/"
        )

    def test_ghost_mode_stays_on_the_local_ladder(self, monkeypatch):
        assert (
            self._resolve(monkeypatch, "openrouter/openai/gpt-4o", ModelTier.QUALITY, ghost=True)
            == "ollama/qwen2.5:32b"
        )

    def test_an_explicit_tier_beats_the_table(self, monkeypatch):
        from raven.core.config import settings

        monkeypatch.setattr(settings, "model_fast", "groq/qwen/qwen3.8-27b")
        monkeypatch.setattr(settings, "default_model", "ollama/llama3")
        monkeypatch.setattr(settings, "ghost_mode", False)
        assert _resolve_default_model(ModelTier.FAST) == "groq/qwen/qwen3.8-27b"
