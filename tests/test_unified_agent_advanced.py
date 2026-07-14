from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.context_router import TaskType
from raven.core.unified_agent import AgentMode, UnifiedAgent


class TestLLMFallback:
    async def test_add_fallback(self) -> None:
        agent = UnifiedAgent()
        agent.add_llm_fallback("provider_b")
        assert len(agent._llm_fallbacks) == 1

    async def test_add_multiple_fallbacks(self) -> None:
        agent = UnifiedAgent()
        agent.add_llm_fallback("p1")
        agent.add_llm_fallback("p2")
        assert len(agent._llm_fallbacks) == 2

    async def test_all_fallbacks_fail(self) -> None:
        agent = UnifiedAgent(llm_provider=AsyncMock(side_effect=RuntimeError("primary down")))
        agent.add_llm_fallback(AsyncMock(side_effect=ValueError("fallback down")))
        with pytest.raises(RuntimeError, match="primary down"):
            await agent._llm_call_with_fallback([{"role": "user", "content": "hi"}])

    async def test_fallback_succeeds(self) -> None:
        primary = AsyncMock(side_effect=RuntimeError("fail"))
        fallback = AsyncMock(return_value={"content": "fallback worked"})
        agent = UnifiedAgent(llm_provider=primary)
        agent.add_llm_fallback(fallback)
        result = await agent._llm_call_with_fallback([{"role": "user", "content": "hi"}])
        assert result["content"] == "fallback worked"

    async def test_primary_succeeds_no_fallback(self) -> None:
        primary = AsyncMock(return_value={"content": "primary ok"})
        agent = UnifiedAgent(llm_provider=primary)
        result = await agent._llm_call_with_fallback([{"role": "user", "content": "hi"}])
        assert result["content"] == "primary ok"

    async def test_no_providers_raises(self) -> None:
        agent = UnifiedAgent(llm_provider=None)
        with pytest.raises(RuntimeError, match="No LLM providers available"):
            await agent._llm_call_with_fallback([{"role": "user", "content": "hi"}])


class TestProcessWithRecovery:
    async def test_first_attempt_succeeds(self) -> None:
        agent = UnifiedAgent()
        agent.process = AsyncMock(return_value="ok")  # type: ignore[method-assign]
        result = await agent.process_with_recovery("hi")
        assert result == "ok"

    async def test_retry_on_failure(self) -> None:
        agent = UnifiedAgent()
        agent.process = AsyncMock(side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), "ok"])  # type: ignore[method-assign]
        result = await agent.process_with_recovery("hi", max_retries=2)
        assert result == "ok"
        assert agent.process.call_count == 3

    async def test_exhausted_retries_raises(self) -> None:
        agent = UnifiedAgent()
        agent.process = AsyncMock(side_effect=RuntimeError("always fail"))  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="always fail"):
            await agent.process_with_recovery("hi", max_retries=1)
        assert agent.process.call_count == 2

    async def test_cancelled_error_not_caught(self) -> None:
        agent = UnifiedAgent()
        agent.process = AsyncMock(side_effect=asyncio.CancelledError())  # type: ignore[method-assign]
        with pytest.raises(asyncio.CancelledError):
            await agent.process_with_recovery("hi")


class TestStreamProcess:
    async def test_stream_yields_messages(self) -> None:
        agent = UnifiedAgent()
        agent.process = AsyncMock(return_value="final answer")  # type: ignore[method-assign]
        agent._on_message = AsyncMock()
        tokens = [t async for t in agent.stream_process("hi")]
        assert "final answer" in tokens

    async def test_stream_with_on_message(self) -> None:
        on_message = AsyncMock()
        agent = UnifiedAgent(on_message=on_message)
        agent.process = AsyncMock(return_value="done")  # type: ignore[method-assign]
        tokens = [t async for t in agent.stream_process("hi")]
        assert tokens
        assert any("done" in t for t in tokens)

    async def test_stream_error_handling(self) -> None:
        agent = UnifiedAgent()
        agent.process = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        tokens = [t async for t in agent.stream_process("hi")]
        assert any("error" in t for t in tokens)


class TestContextManagement:
    async def test_estimate_tokens_empty(self) -> None:
        agent = UnifiedAgent()
        assert agent._estimate_tokens([]) == 0

    async def test_estimate_tokens_some(self) -> None:
        agent = UnifiedAgent()
        msgs = [{"role": "user", "content": "hello world"}]
        assert agent._estimate_tokens(msgs) > 0

    async def test_estimate_tokens_ignores_non_dict(self) -> None:
        agent = UnifiedAgent()
        msgs = ["not a dict", {"role": "user", "content": "hi"}]
        assert agent._estimate_tokens(msgs) > 0

    async def test_maybe_summarize_below_threshold(self) -> None:
        agent = UnifiedAgent(max_context_tokens=100_000)
        with patch.object(agent, "_estimate_tokens", return_value=10_000):
            mock_agent = MagicMock()
            mock_agent.conversation.get_messages.return_value = [{"role": "user", "content": "hi"}]
            result = await agent._maybe_summarize(mock_agent)
            assert result is False

    async def test_maybe_summarize_empty_messages(self) -> None:
        agent = UnifiedAgent()
        mock_agent = MagicMock()
        mock_agent.conversation.get_messages.return_value = []
        result = await agent._maybe_summarize(mock_agent)
        assert result is False

    async def test_maybe_summarize_mock_conversation_error(self) -> None:
        agent = UnifiedAgent()
        mock_agent = MagicMock()
        mock_agent.conversation.get_messages.side_effect = RuntimeError("mock fail")
        result = await agent._maybe_summarize(mock_agent)
        assert result is False


class TestBuildAgentConfig:
    def test_coding_config(self) -> None:
        agent = UnifiedAgent(max_steps=15)
        config = agent._build_agent_config(TaskType.CODING)
        assert config.diff_preview is True
        assert config.proactive_scan is True
        assert config.plan_mode is False
        assert config.structured_output is False
        assert config.max_steps == 15

    def test_automation_config(self) -> None:
        agent = UnifiedAgent()
        config = agent._build_agent_config(TaskType.AUTOMATION)
        assert config.diff_preview is False
        assert config.proactive_scan is False
        assert config.plan_mode is False

    def test_query_config(self) -> None:
        agent = UnifiedAgent()
        config = agent._build_agent_config(TaskType.QUERY)
        assert config.plan_mode is True
        assert config.structured_output is True

    def test_hybrid_config(self) -> None:
        agent = UnifiedAgent()
        config = agent._build_agent_config(TaskType.HYBRID)
        assert config.diff_preview is True
        assert config.proactive_scan is True


class TestBuildConfigAlias:
    def test_backward_compat(self) -> None:
        agent = UnifiedAgent(max_steps=5)
        config = agent._build_config(TaskType.CODING)
        assert config.max_steps == 5
