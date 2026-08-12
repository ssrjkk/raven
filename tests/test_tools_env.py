from __future__ import annotations

import os
from unittest.mock import patch

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.env import _is_sensitive, _safe_val, env_get, env_list, register_env_tools


class TestIsSensitive:
    def test_keyword_match(self) -> None:
        assert _is_sensitive("OPENAI_API_KEY") is True
        assert _is_sensitive("GITHUB_TOKEN") is True
        assert _is_sensitive("DB_PASSWORD") is True
        assert _is_sensitive("BASIC_AUTH_USER") is True

    def test_non_sensitive(self) -> None:
        assert _is_sensitive("APP_NAME") is False
        assert _is_sensitive("RAVEN_WORKSPACE") is False

    def test_case_insensitive(self) -> None:
        assert _is_sensitive("api_key") is True


class TestSafeVal:
    def test_non_sensitive_passthrough(self) -> None:
        assert _safe_val("APP_NAME", "raven") == "raven"

    def test_sensitive_long_masked(self) -> None:
        assert _safe_val("API_KEY", "sk-1234567890abcd") == "sk-1...abcd"

    def test_sensitive_short_masked(self) -> None:
        assert _safe_val("API_KEY", "sk-short") == "****"

    def test_sensitive_placeholder_values_pass_through(self) -> None:
        assert _safe_val("API_KEY", "sk-...") == "sk-..."
        assert _safe_val("API_KEY", "0") == "0"
        assert _safe_val("API_KEY", "") == ""

    def test_sensitive_whitespace_placeholder(self) -> None:
        assert _safe_val("API_KEY", " 0 ") == " 0 "


class TestEnvGet:
    def test_existing(self) -> None:
        with patch.dict("os.environ", {"TEST_ENV_VAR": "test_value"}, clear=False):
            result = env_get("TEST_ENV_VAR")
            assert "test_value" in result

    def test_missing(self) -> None:
        assert env_get("NONEXISTENT_VAR_XYZ") == "Environment variable NONEXISTENT_VAR_XYZ not set"

    def test_sensitive_masked(self) -> None:
        with patch.dict("os.environ", {"API_KEY": "sk-abc123def456ghi"}, clear=False):
            result = env_get("API_KEY")
            assert result == "sk-a...6ghi"
            assert "abc123def456ghi" not in result

    def test_sensitive_short_masked(self) -> None:
        with patch.dict("os.environ", {"API_KEY": "sk-short"}, clear=False):
            assert env_get("API_KEY") == "****"

    def test_sensitive_placeholder_passthrough(self) -> None:
        with patch.dict("os.environ", {"API_KEY": "sk-..."}, clear=False):
            assert env_get("API_KEY") == "sk-..."


class TestEnvList:
    def test_sorted_and_masked(self) -> None:
        envs = {"AAA": "1", "B_TOKEN": "verysecretvalue12345", "CCC": "2"}
        with patch.dict("os.environ", envs, clear=True):
            result = env_list()
            lines = result.split("\n")
            assert lines[0] == "AAA=1"
            assert lines[1] == "B_TOKEN=very...2345"
            assert lines[2] == "CCC=2"

    def test_limited_to_50(self) -> None:
        envs = {f"K{i:03d}": "v" for i in range(60)}
        with patch.dict("os.environ", envs, clear=True):
            result = env_list()
            assert len(result.split("\n")) == 50


class TestRegisterEnvTools:
    def test_registers_tools(self) -> None:
        registry = ToolRegistry()
        register_env_tools(registry)
        assert registry.count == 2
        tool = registry.get("env_get")
        assert tool is not None
        assert tool.category == "system"
