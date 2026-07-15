from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.context_router import TaskType
from raven.core.unified_agent import AgentMode, HybridSession, UnifiedAgent


class TestAgentMode:
    def test_enum_values(self) -> None:
        assert AgentMode.CODING.value == "coding"
        assert AgentMode.AUTOMATION.value == "automation"
        assert AgentMode.HYBRID.value == "hybrid"
        assert AgentMode.QUERY.value == "query"

    def test_enum_members(self) -> None:
        assert set(AgentMode.__members__) == {"CODING", "AUTOMATION", "HYBRID", "QUERY"}

    def test_enum_is_str_enum(self) -> None:
        assert issubclass(AgentMode, str)


class TestHybridSession:
    def test_create_session(self) -> None:
        session = HybridSession(session_id="sess-001", mode=AgentMode.HYBRID)
        assert session.session_id == "sess-001"
        assert session.mode == AgentMode.HYBRID
        assert session.messages == []
        assert isinstance(session.created_at, datetime)

    def test_session_created_at_utc(self) -> None:
        session = HybridSession(session_id="sess-002", mode=AgentMode.CODING)
        assert session.created_at.tzinfo is not None
        assert session.created_at.tzinfo.utcoffset(session.created_at) == UTC.utcoffset(None)

    def test_add_message_without_task_type(self) -> None:
        session = HybridSession(session_id="sess-003", mode=AgentMode.CODING)
        session.add_message("user", "hello")
        assert len(session.messages) == 1
        assert session.messages[0] == {"role": "user", "content": "hello"}

    def test_add_message_with_task_type(self) -> None:
        session = HybridSession(session_id="sess-004", mode=AgentMode.HYBRID)
        session.add_message("assistant", "done", task_type="coding")
        assert session.messages[0] == {"role": "assistant", "content": "done", "task_type": "coding"}

    def test_multiple_messages(self) -> None:
        session = HybridSession(session_id="sess-005", mode=AgentMode.HYBRID)
        session.add_message("user", "q1")
        session.add_message("assistant", "a1", task_type="coding")
        session.add_message("user", "q2")
        assert len(session.messages) == 3


class TestUnifiedAgentUpgraded:
    def test_create_agent(self) -> None:
        agent = UnifiedAgent(name="test", max_steps=10)
        assert agent.name == "test"
        assert agent.task_type == TaskType.QUERY
        assert agent.mode == AgentMode.QUERY

    def test_event_emitter_property(self) -> None:
        agent = UnifiedAgent()
        assert agent.event_emitter is not None

    def test_tool_registry_property(self) -> None:
        agent = UnifiedAgent()
        assert agent.tool_registry is not None

    def test_shared_memory_property(self) -> None:
        agent = UnifiedAgent()
        assert agent.shared_memory is not None

    def test_abort_no_agent(self) -> None:
        agent = UnifiedAgent()
        agent.abort()

    @patch.object(UnifiedAgent, "handle_coding", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_automation", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_query", new_callable=AsyncMock)
    async def test_process_dispatches_coding(
        self, mock_query: AsyncMock, mock_hybrid: AsyncMock, mock_automation: AsyncMock, mock_coding: AsyncMock
    ) -> None:
        agent = UnifiedAgent()
        mock_coding.return_value = "code result"
        result = await agent.process("write a function")
        assert result == "code result"
        mock_coding.assert_awaited_once()

    @patch.object(UnifiedAgent, "handle_coding", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_automation", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_query", new_callable=AsyncMock)
    async def test_process_dispatches_automation(
        self, mock_query: AsyncMock, mock_hybrid: AsyncMock, mock_automation: AsyncMock, mock_coding: AsyncMock
    ) -> None:
        agent = UnifiedAgent()
        mock_automation.return_value = "auto result"
        result = await agent.process("schedule a backup every day")
        assert result == "auto result"
        mock_automation.assert_awaited_once()

    @patch.object(UnifiedAgent, "handle_coding", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_automation", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_query", new_callable=AsyncMock)
    async def test_process_dispatches_hybrid(
        self, mock_query: AsyncMock, mock_hybrid: AsyncMock, mock_automation: AsyncMock, mock_coding: AsyncMock
    ) -> None:
        agent = UnifiedAgent()
        mock_hybrid.return_value = "hybrid result"
        result = await agent.process("write a script and schedule it")
        assert result == "hybrid result"
        mock_hybrid.assert_awaited_once()

    @patch.object(UnifiedAgent, "handle_coding", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_automation", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_query", new_callable=AsyncMock)
    async def test_process_dispatches_query(
        self, mock_query: AsyncMock, mock_hybrid: AsyncMock, mock_automation: AsyncMock, mock_coding: AsyncMock
    ) -> None:
        agent = UnifiedAgent()
        mock_query.return_value = "query result"
        result = await agent.process("what is the weather?")
        assert result == "query result"
        mock_query.assert_awaited_once()

    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    async def test_hybrid_session_create(self, mock_hybrid: AsyncMock) -> None:
        agent = UnifiedAgent()
        session = agent.create_hybrid_session("sess-101", mode=AgentMode.HYBRID)
        assert isinstance(session, HybridSession)
        assert session.session_id == "sess-101"
        assert session.mode == AgentMode.HYBRID

    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    async def test_hybrid_session_get(self, mock_hybrid: AsyncMock) -> None:
        agent = UnifiedAgent()
        agent.create_hybrid_session("sess-102")
        session = agent.get_hybrid_session("sess-102")
        assert session is not None
        assert session.session_id == "sess-102"

    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    async def test_hybrid_session_get_missing(self, mock_hybrid: AsyncMock) -> None:
        agent = UnifiedAgent()
        session = agent.get_hybrid_session("nonexistent")
        assert session is None

    @patch("ravencode.runtime.agent_core.ReActAgent")
    async def test_handle_coding_config(self, mock_react: AsyncMock) -> None:
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value="ok")
        mock_react.return_value = mock_instance

        agent = UnifiedAgent()
        result = await agent.handle_coding("write a function")

        assert result == "ok"
        assert agent.mode == AgentMode.CODING
        assert agent.task_type == TaskType.CODING
        _, kwargs = mock_react.call_args
        config = kwargs["config"]
        assert config.diff_preview is True
        assert config.proactive_scan is True
        assert config.plan_mode is False

    @patch("ravencode.runtime.agent_core.ReActAgent")
    async def test_handle_automation_config(self, mock_react: AsyncMock) -> None:
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value="ok")
        mock_react.return_value = mock_instance

        agent = UnifiedAgent()
        result = await agent.handle_automation("schedule a task")

        assert result == "ok"
        assert agent.mode == AgentMode.AUTOMATION
        assert agent.task_type == TaskType.AUTOMATION
        _, kwargs = mock_react.call_args
        config = kwargs["config"]
        assert config.diff_preview is False
        assert config.proactive_scan is False
        assert config.plan_mode is False

    @patch("ravencode.runtime.agent_core.ReActAgent")
    async def test_handle_query_config(self, mock_react: AsyncMock) -> None:
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value="answer")
        mock_react.return_value = mock_instance

        agent = UnifiedAgent()
        result = await agent.handle_query("what is 2+2?")

        assert result == "answer"
        assert agent.mode == AgentMode.QUERY
        assert agent.task_type == TaskType.QUERY
        _, kwargs = mock_react.call_args
        config = kwargs["config"]
        assert config.plan_mode is True
        assert config.structured_output is True

    @patch.object(UnifiedAgent, "handle_coding", new_callable=AsyncMock)
    @patch.object(UnifiedAgent, "handle_automation", new_callable=AsyncMock)
    async def test_handle_hybrid_sequential(self, mock_automation: AsyncMock, mock_coding: AsyncMock) -> None:
        mock_coding.return_value = "code output"
        mock_automation.return_value = "auto output"

        agent = UnifiedAgent()
        result = await agent.handle_hybrid("write a script then deploy it")

        assert agent.mode == AgentMode.HYBRID
        assert agent.task_type == TaskType.HYBRID
        mock_coding.assert_awaited_once_with("write a script then deploy it")
        mock_automation.assert_awaited_once()
        args, _ = mock_automation.call_args
        assert "code output" in args[0]
        assert "Coding" in result
        assert "Automation" in result

    @patch.object(UnifiedAgent, "handle_hybrid", new_callable=AsyncMock)
    async def test_process_sets_mode(self, mock_hybrid: AsyncMock) -> None:
        mock_hybrid.return_value = "ok"
        agent = UnifiedAgent()
        await agent.process("write a script and schedule it")
        assert agent.mode == AgentMode.HYBRID
        assert agent.task_type == TaskType.HYBRID

    @patch("ravencode.runtime.agent_core.ReActAgent")
    async def test_process_hybrid_session_persistence(self, mock_react: AsyncMock) -> None:
        mock_instance = AsyncMock()
        mock_instance.run = AsyncMock(return_value="result")
        mock_react.return_value = mock_instance

        agent = UnifiedAgent()
        agent.create_hybrid_session("sess-persist", mode=AgentMode.HYBRID)

        await agent.process_hybrid_session("sess-persist", "first message")
        await agent.process_hybrid_session("sess-persist", "second message")

        session = agent.get_hybrid_session("sess-persist")
        assert session is not None
        assert len(session.messages) == 4
        assert session.messages[0] == {"role": "user", "content": "first message"}
        assert session.messages[1]["role"] == "assistant"
        assert session.messages[2] == {"role": "user", "content": "second message"}
        assert session.messages[3]["role"] == "assistant"

    async def test_process_hybrid_session_not_found(self) -> None:
        agent = UnifiedAgent()
        with pytest.raises(ValueError, match="Hybrid session 'bad-id' not found"):
            await agent.process_hybrid_session("bad-id", "hello")

    def test_build_config(self) -> None:
        agent = UnifiedAgent(max_steps=5)
        config = agent._build_config(TaskType.CODING)
        assert config.max_steps == 5
