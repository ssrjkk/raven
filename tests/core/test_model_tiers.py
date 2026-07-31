from __future__ import annotations

from raven.core.model_tiers import ModelTier, _estimate_complexity


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
        messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}, {"role": "user", "content": "what is a decorator"}]
        assert _estimate_complexity(messages) == "medium"

    def test_complex_code_request(self):
        messages = [{"role": "user", "content": "implement a binary search tree in python with insert, delete, and search methods"}]
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
