from __future__ import annotations

import pytest

from ravencode.core.feature_flags import FeatureFlags, feature_flags


class TestFeatureFlags:
    def test_defaults(self) -> None:
        ff = FeatureFlags()
        assert ff.is_enabled("redis_rate_limiter") is False
        assert ff.all_flags() == {"redis_rate_limiter": False}

    def test_unknown_flag_uses_default(self) -> None:
        ff = FeatureFlags()
        assert ff.is_enabled("nonexistent") is False
        assert ff.is_enabled("nonexistent", True) is True

    def test_set(self) -> None:
        ff = FeatureFlags()
        ff.set("redis_rate_limiter", True)
        assert ff.is_enabled("redis_rate_limiter") is True

    def test_all_flags_is_copy(self) -> None:
        ff = FeatureFlags()
        snapshot = ff.all_flags()
        ff.set("redis_rate_limiter", True)
        assert snapshot["redis_rate_limiter"] is False

    @pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "ON"])
    def test_an_on_value_turns_the_flag_on(self, monkeypatch, raw: str) -> None:
        ff = FeatureFlags()
        monkeypatch.setenv("FF_REDIS_RATE_LIMITER", raw)
        ff._load_from_env()
        assert ff.is_enabled("redis_rate_limiter") is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off"])
    def test_an_off_value_keeps_the_flag_off(self, monkeypatch, raw: str) -> None:
        ff = FeatureFlags()
        monkeypatch.setenv("FF_REDIS_RATE_LIMITER", raw)
        ff._load_from_env()
        assert ff.is_enabled("redis_rate_limiter") is False

    def test_a_value_that_is_not_on_or_off_is_reported_not_guessed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from loguru import logger

        ff = FeatureFlags()
        ff.set("redis_rate_limiter", True)
        warnings: list[str] = []
        sink_id = logger.add(lambda record: warnings.append(str(record)), level="WARNING")
        try:
            monkeypatch.setenv("FF_REDIS_RATE_LIMITER", "banana")
            ff._load_from_env()
        finally:
            logger.remove(sink_id)
        assert ff.is_enabled("redis_rate_limiter") is True, "a bad value silently flipped the flag"
        assert any("FF_REDIS_RATE_LIMITER" in line for line in warnings), warnings

    def test_the_env_var_is_optional(self, monkeypatch) -> None:
        monkeypatch.delenv("FF_REDIS_RATE_LIMITER", raising=False)
        ff = FeatureFlags()
        assert ff.is_enabled("redis_rate_limiter") is False


def test_module_singleton_is_featureflags() -> None:
    assert isinstance(feature_flags, FeatureFlags)
