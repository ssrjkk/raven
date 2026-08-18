from __future__ import annotations

import pytest

from ravencode.core.feature_flags import FeatureFlags, feature_flags


class TestFeatureFlags:
    def test_defaults(self) -> None:
        ff = FeatureFlags()
        assert ff.is_enabled("new_planner_v2") is False
        assert ff.is_enabled("claude_3_opus") is True

    def test_unknown_flag_uses_default(self) -> None:
        ff = FeatureFlags()
        assert ff.is_enabled("nonexistent") is False
        assert ff.is_enabled("nonexistent", True) is True

    def test_set(self) -> None:
        ff = FeatureFlags()
        ff.set("new_planner_v2", True)
        assert ff.is_enabled("new_planner_v2") is True

    def test_all_flags_is_copy(self) -> None:
        ff = FeatureFlags()
        snapshot = ff.all_flags()
        ff.set("new_planner_v2", True)
        assert snapshot["new_planner_v2"] is False

    @pytest.mark.parametrize(
        "raw,expected",
        [("1", True), ("true", True), ("yes", True), ("0", False), ("false", False), ("no", False), ("banana", False)],
    )
    def test_load_from_env(self, monkeypatch, raw: str, expected: bool) -> None:
        ff = FeatureFlags()
        monkeypatch.setenv("FF_CLAUDE_3_OPUS", raw)
        ff._load_from_env()
        assert ff.is_enabled("claude_3_opus") is expected

    def test_module_singleton_is_featureflags(self) -> None:
        assert isinstance(feature_flags, FeatureFlags)
