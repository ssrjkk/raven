from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.core.agent.agent import Agent, AgentConfig
from raven.core.agent.registry import AgentRegistry
from raven.core.models import PluginTool, Session


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get_session_messages = AsyncMock(return_value=[])
    db.save_message = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    from raven.core.llm import LLMResponse
    llm.complete = AsyncMock(return_value=LLMResponse(content="Hello from Raven!", finish_reason="stop"))
    return llm


@pytest.fixture
def session():
    return Session(id="test-session", channel="telegram", user_id="user1")


@pytest.fixture
def tools():
    async def ping() -> str:
        return "pong"
    return [PluginTool(name="ping", description="Ping test", parameters={"type": "object", "properties": {}}, handler=ping)]


@pytest.fixture
def agent(session, tools, mock_db, mock_llm):
    config = AgentConfig(max_tool_rounds=3, use_memory=False)
    return Agent(session=session, tools=tools, db=mock_db, llm=mock_llm, config=config)


class TestAgent:
    async def test_run_basic(self, agent):
        tokens = []
        async for token in agent.run("hello"):
            tokens.append(token)
        result = "".join(tokens)
        assert "Hello from Raven" in result

    async def test_run_with_tool(self, session, tools, mock_db):
        llm = AsyncMock()
        from raven.core.llm import LLMResponse, ToolCall
        llm.complete = AsyncMock(return_value=LLMResponse(
            content="",
            tool_calls=[ToolCall(id="call1", name="ping", arguments={})],
            finish_reason="tool_calls",
        ))

        config = AgentConfig(max_tool_rounds=3, use_memory=False)
        agent = Agent(session=session, tools=tools, db=mock_db, llm=llm, config=config)
        async for _ in agent.run("ping"):
            pass

    async def test_tool_execution(self, agent):
        from raven.core.llm import ToolCall
        tc = ToolCall(id="call1", name="ping", arguments={})
        result = await agent._execute_tool(tc)
        assert "result" in result
        assert result["result"] == "pong"

    async def test_tool_execution_unknown(self, agent):
        from raven.core.llm import ToolCall
        tc = ToolCall(id="call1", name="nonexistent", arguments={})
        result = await agent._execute_tool(tc)
        assert "error" in result

    async def test_agent_config_defaults(self):
        config = AgentConfig()
        assert config.max_tool_rounds == 10
        assert config.use_memory is True
        assert config.agent_id == "default"

    async def test_build_system_prompt(self, agent):
        prompt = agent._build_system_prompt()
        assert "Raven" in prompt


class TestAgentRegistry:
    @pytest.fixture
    def registry(self, mock_db, mock_llm):
        return AgentRegistry(db=mock_db, llm=mock_llm, tools=[])

    def test_default_agents(self, registry):
        registry.setup_defaults()
        assert len(registry.list_agents()) == 3
        assert "default" in [a["id"] for a in registry.list_agents()]
        assert "coder" in [a["id"] for a in registry.list_agents()]

    def test_channel_mapping(self, registry):
        registry.setup_defaults()
        assert registry.get_agent_for_channel("telegram") == "default"
        assert registry.get_agent_for_channel("webchat") == "assistant"

    def test_create_agent(self, registry, mock_db, mock_llm):
        registry.setup_defaults()
        session = Session(id="s1", channel="telegram", user_id="u1")
        agent = registry.create_agent(session)
        assert agent is not None
        assert agent.session.id == "s1"
