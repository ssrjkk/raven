# mypy: ignore-errors
from __future__ import annotations

from unittest.mock import patch

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.env import env_get, env_list, register_env_tools


class TestEnvTools:
    async def test_env_get_existing(self) -> None:
        with patch.dict("os.environ", {"TEST_ENV_VAR": "test_value"}, clear=False):
            result = env_get("TEST_ENV_VAR")
            assert "test_value" in result

    async def test_env_get_missing(self) -> None:
        result = env_get("NONEXISTENT_VAR_XYZ")
        assert "not set" in result

    async def test_env_get_sensitive_masked(self) -> None:
        with patch.dict("os.environ", {"API_KEY": "sk-abc123def456ghi"}, clear=False):
            result = env_get("API_KEY")
            assert "sk-a" in result
            assert "ghi" in result
            assert "abc123def456ghi" not in result

    async def test_env_list(self) -> None:
        with patch.dict("os.environ", {"EXISTING_KEY": "value"}, clear=False):
            result = env_list()
            assert isinstance(result, str)
            assert len(result) > 0

    async def test_register_tools(self) -> None:
        registry = ToolRegistry()
        register_env_tools(registry)
        assert registry.get("env_get") is not None
        assert registry.get("env_list") is not None
