from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ravencode.api.client import AIOSClient, AIResponse, reset_shared_llm


class TestRavencodeApiClient:
    @pytest.fixture(autouse=True)
    def _isolate_shared_llm(self):
        reset_shared_llm()
        yield
        reset_shared_llm()
    @patch("raven.core.llm.LLMRouter")
    @patch("ravencode.api.client.settings")
    def test_ask_success(self, mock_settings, mock_llm_cls):
        mock_settings.default_model = "gpt-4"
        mock_llm = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = "hello"
        mock_llm.complete = AsyncMock(return_value=mock_resp)
        mock_llm_cls.return_value = mock_llm

        import asyncio

        r = asyncio.run(AIOSClient().ask("hi", task="code"))
        assert isinstance(r, AIResponse)
        assert r.text == "hello"
        assert r.provider == "openrouter"

    @patch("raven.core.llm.LLMRouter")
    @patch("ravencode.api.client.settings")
    def test_ask_api_error(self, mock_settings, mock_llm_cls):
        mock_settings.default_model = "gpt-4"
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("API down"))
        mock_llm_cls.return_value = mock_llm

        import asyncio

        r = asyncio.run(AIOSClient().ask("hi"))
        assert isinstance(r, AIResponse)
        assert "API down" in r.text

    def test_ai_response_defaults(self):
        r = AIResponse(text="ok", model="gpt4", provider="openai")
        assert r.usage is None

    @patch("raven.core.llm.LLMRouter", side_effect=RuntimeError("no API keys"))
    @patch("ravencode.api.client.settings")
    def test_degraded_no_llm(self, mock_settings, mock_llm_cls):
        import asyncio

        r = asyncio.run(AIOSClient().ask("hi"))
        assert "unavailable" in r.text


class TestRavencodeInit:
    def test_lazy_imports(self):
        from ravencode import (
            AgentConfig,
            AIOSClient,
            CheckpointManager,
            FileWatcher,
            LSPClient,
            MCPServer,
            MemoryStore,
            MultiAgentOrchestrator,
            Orchestrator,
            PermissionManager,
            Plugin,
            PluginRegistry,
            ResponseCache,
            Sandbox,
            SessionStore,
            ShellExecutor,
            UndoManager,
            apply_patch,
            auto_commit,
            format_file,
            smart_edit,
        )

        assert AIOSClient is not None
        assert Orchestrator is not None
        assert ShellExecutor is not None
        assert AgentConfig is not None
        assert MemoryStore is not None
        assert UndoManager is not None
        assert PermissionManager is not None
        assert Plugin is not None
        assert PluginRegistry is not None
        assert ResponseCache is not None
        assert LSPClient is not None
        assert CheckpointManager is not None
        assert FileWatcher is not None
        assert MCPServer is not None
        assert Sandbox is not None
        assert MultiAgentOrchestrator is not None
        assert SessionStore is not None
        assert auto_commit is not None
        assert format_file is not None
        assert smart_edit is not None
        assert apply_patch is not None

    def test_all_exported(self):
        import ravencode

        for name in ravencode.__all__:
            assert hasattr(ravencode, name), f"Missing {name} in ravencode module"


class TestRavencodeAgentResult:
    def test_defaults(self):
        from ravencode.agents.orchestrator import AgentResult

        r = AgentResult(agent="test", success=True)
        assert r.error is None
        assert r.data is None

    def test_with_error(self):
        from ravencode.agents.orchestrator import AgentResult

        r = AgentResult(agent="test", success=False, error="fail")
        assert r.error == "fail"
