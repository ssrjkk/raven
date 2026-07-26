from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.cli.onboard import _mask, _prompt_channels, _prompt_llm, _prompt_port, _prompt_security


class TestPromptLlm:
    def test_openrouter_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["openrouter", "sk-test-key", ""])
            result = _prompt_llm(config)
            assert result.get("openrouter_api_key") == "sk-test-key"
            assert "default_model" in result

    def test_anthropic_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["anthropic", "sk-ant-key", ""])
            result = _prompt_llm(config)
            assert result.get("anthropic_api_key") == "sk-ant-key"
            assert "default_model" in result

    def test_openai_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["openai", "sk-openai-key", ""])
            result = _prompt_llm(config)
            assert result.get("openai_api_key") == "sk-openai-key"
            assert "default_model" in result

    def test_ollama_sets_config(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(side_effect=["ollama", "http://localhost:11434", ""])
            result = _prompt_llm(config)
            assert result.get("ollama_base_url") == "http://localhost:11434"
            assert "default_model" in result


class TestPromptChannels:
    def test_no_channels(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Confirm") as MockConfirm:
            MockConfirm.ask = MagicMock(return_value=False)
            result = _prompt_channels(config)
            assert "discord_bot_token" not in result
            assert "slack_bot_token" not in result

    def test_discord_channel(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Confirm") as MockConfirm, patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockConfirm.ask = MagicMock(side_effect=[True, False])
            MockPrompt.ask = MagicMock(return_value="discord-token-123")
            result = _prompt_channels(config)
            assert result.get("discord_bot_token") == "discord-token-123"


class TestPromptSecurity:
    def test_default_pairing_policy(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt, patch("raven.cli.onboard.Confirm") as MockConfirm:
            MockPrompt.ask = MagicMock(return_value="pairing")
            MockConfirm.ask = MagicMock(return_value=False)
            result = _prompt_security(config)
            assert result.get("dm_policy") == "pairing"

    def test_open_policy(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt, patch("raven.cli.onboard.Confirm") as MockConfirm:
            MockPrompt.ask = MagicMock(return_value="open")
            MockConfirm.ask = MagicMock(return_value=False)
            result = _prompt_security(config)
            assert result.get("dm_policy") == "open"


class TestPromptPort:
    def test_default_port(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(return_value="")
            result = _prompt_port(config)
            assert result.get("web_port") == 18888

    def test_custom_port(self):
        config: dict[str, Any] = {}
        with patch("raven.cli.onboard.Prompt") as MockPrompt:
            MockPrompt.ask = MagicMock(return_value="8080")
            result = _prompt_port(config)
            assert result.get("web_port") == 8080


class TestMask:
    def test_mask_short_string_no_mask(self):
        result = _mask("abc")
        assert result == "abc"

    def test_mask_exactly_8_chars_no_mask(self):
        result = _mask("12345678")
        assert result == "12345678"

    def test_mask_long_string(self):
        result = _mask("sk-1234567890abcdef")
        assert result.startswith("sk-")
        assert "****" in result
        assert result.endswith("cdef")

    def test_mask_empty(self):
        result = _mask("")
        assert result == ""

    def test_mask_9_chars_masked(self):
        result = _mask("123456789")
        assert "****" in result
        assert result.startswith("1234")
        assert result.endswith("6789")
