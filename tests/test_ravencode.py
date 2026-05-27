from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


from ravencode.api.client import AIOSClient, AIResponse


class TestRavencodeApiClient:
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

    @patch("raven.core.llm.LLMRouter",
           side_effect=RuntimeError("no API keys"))
    @patch("ravencode.api.client.settings")
    def test_degraded_no_llm(self, mock_settings, mock_llm_cls):
        import asyncio
        r = asyncio.run(AIOSClient().ask("hi"))
        assert "unavailable" in r.text


class TestRavencodeInit:
    def test_lazy_imports(self):
        from ravencode import AIOSClient, Orchestrator, ShellExecutor
        assert AIOSClient is not None
        assert Orchestrator is not None
        assert ShellExecutor is not None

    def test_all_exported(self):
        import ravencode
        assert "AIOSClient" in ravencode.__all__
        assert "Orchestrator" in ravencode.__all__
        assert "ShellExecutor" in ravencode.__all__


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
