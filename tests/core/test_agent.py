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

    return [
        PluginTool(name="ping", description="Ping test", parameters={"type": "object", "properties": {}}, handler=ping)
    ]


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

    async def test_run_empty_response_fallback(self, session, tools, mock_db):
        from raven.core.llm import LLMResponse

        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=LLMResponse(content="", finish_reason="stop"))
        config = AgentConfig(max_tool_rounds=3, use_memory=False)
        agent = Agent(session=session, tools=tools, db=mock_db, llm=llm, config=config)
        tokens = [t async for t in agent.run("hello")]
        assert "".join(tokens) == "I couldn't generate a response to that. Please try rephrasing your message."

    async def test_run_with_tool(self, session, tools, mock_db):
        llm = AsyncMock()
        from raven.core.llm import LLMResponse, ToolCall

        llm.complete = AsyncMock(
            return_value=LLMResponse(
                content="",
                tool_calls=[ToolCall(id="call1", name="ping", arguments={})],
                finish_reason="tool_calls",
            )
        )

        config = AgentConfig(max_tool_rounds=3, use_memory=False)
        agent = Agent(session=session, tools=tools, db=mock_db, llm=llm, config=config)
        async for _ in agent.run("ping"):
            pass

    async def test_tool_execution(self, agent, session, tools, mock_db, mock_llm):
        from raven.core.llm import ToolCall
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        agent = Agent(
            session=session,
            tools=tools,
            db=mock_db,
            llm=mock_llm,
            config=AgentConfig(max_tool_rounds=3, use_memory=False),
            tool_policy=ToolPolicyEvaluator("full", "", ""),  # type: ignore[arg-type]
        )
        tc = ToolCall(id="call1", name="ping", arguments={})
        result = await agent._execute_tool(tc)
        assert "result" in result
        assert result["result"] == "pong"

    async def test_tool_execution_unknown(self, agent):
        from raven.core.llm import ToolCall

        tc = ToolCall(id="call1", name="nonexistent", arguments={})
        result = await agent._execute_tool(tc)
        assert "error" in result

    async def test_run_caps_tool_calls_per_round(self, session, mock_db):
        from raven.core.llm import LLMResponse, ToolCall

        executed: list[str] = []

        async def ping() -> str:
            executed.append("ping")
            return "pong"

        ping_tool = PluginTool(
            name="ping",
            description="Ping test",
            parameters={"type": "object", "properties": {}},
            handler=ping,
        )
        calls = [ToolCall(id=f"call{i}", name="ping", arguments={}) for i in range(12)]
        llm = AsyncMock()
        llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(content="", tool_calls=calls, finish_reason="tool_calls"),
                LLMResponse(content="done", finish_reason="stop"),
            ]
        )
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        config = AgentConfig(max_tool_rounds=3, use_memory=False, max_tool_calls_per_round=8)
        agent = Agent(
            session=session,
            tools=[ping_tool],
            db=mock_db,
            llm=llm,
            config=config,
            tool_policy=ToolPolicyEvaluator("full", "", ""),  # type: ignore[arg-type]
        )
        tokens = [t async for t in agent.run("go")]
        assert len(executed) == 8
        assert "done" in "".join(tokens)

    async def test_run_executes_parallel_tool_calls(self, session, mock_db):
        import asyncio

        from raven.core.llm import LLMResponse, ToolCall
        from raven.core.security.tool_policy import ToolPolicyEvaluator

        order: list[str] = []

        async def ping() -> str:
            order.append("start")
            await asyncio.sleep(0.05)
            order.append("end")
            return "pong"

        ping_tool = PluginTool(
            name="ping",
            description="Ping test",
            parameters={"type": "object", "properties": {}},
            handler=ping,
        )
        calls = [ToolCall(id=f"call{i}", name="ping", arguments={}) for i in range(3)]
        llm = AsyncMock()
        llm.complete = AsyncMock(
            side_effect=[
                LLMResponse(content="", tool_calls=calls, finish_reason="tool_calls"),
                LLMResponse(content="done", finish_reason="stop"),
            ]
        )
        agent = Agent(
            session=session,
            tools=[ping_tool],
            db=mock_db,
            llm=llm,
            config=AgentConfig(max_tool_rounds=3, use_memory=False),
            tool_policy=ToolPolicyEvaluator("full", "", ""),  # type: ignore[arg-type]
        )
        tokens = [t async for t in agent.run("go")]
        assert "done" in "".join(tokens)
        assert order.count("start") == 3 and order.count("end") == 3
        starts = [i for i, x in enumerate(order) if x == "start"]
        ends = [i for i, x in enumerate(order) if x == "end"]
        assert max(starts) < min(ends)

    async def test_agent_config_defaults(self):
        config = AgentConfig()
        assert config.max_tool_rounds == 10
        assert config.max_tool_calls_per_round == 8
        assert config.use_memory is True
        assert config.agent_id == "default"

    async def test_build_system_prompt(self, agent):
        prompt = await agent._build_system_prompt()
        assert "Raven" in prompt


class TestLoopDetection:
    def test_detect_loop_no_tool_calls(self, agent):
        history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
        assert agent._detect_loop(history) is False

    def test_detect_loop_empty_history(self, agent):
        assert agent._detect_loop([]) is False

    def test_detect_loop_few_calls(self, agent):
        history = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "ping"}}]}
            for _ in range(3)
        ]
        assert agent._detect_loop(history) is False

    def test_detect_loop_same_tool_four_times(self, agent):
        history = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "ping"}}]}
            for _ in range(4)
        ]
        assert agent._detect_loop(history) is True

    def test_detect_loop_mixed_tools_no_loop(self, agent):
        history = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": n}}]}
            for n in ("ping", "pong", "ping", "pong")
        ]
        assert agent._detect_loop(history) is False

    def test_detect_loop_empty_tool_calls_list(self, agent):
        history = [{"role": "assistant", "content": "", "tool_calls": []} for _ in range(5)]
        assert agent._detect_loop(history) is False


class TestCompression:
    def test_mark_untrusted_wraps_plain_text(self, agent):
        marked = agent._mark_untrusted("hello world")
        assert marked.startswith("<<<EXTERNAL_UNTRUSTED_CONTENT>>>")
        assert "hello world" in marked
        assert marked.endswith("<<<END_EXTERNAL_CONTENT>>>")

    def test_mark_untrusted_skips_already_marked(self, agent):
        already = "<<<EXTERNAL_UNTRUSTED_CONTENT>>>\nSource: webhook\n---\npayload\n<<<END_EXTERNAL_CONTENT>>>"
        assert agent._mark_untrusted(already) == already

    async def test_compress_short_history_untouched(self, agent):
        messages = [{"role": "user", "content": "a"} for _ in range(5)]
        assert await agent._compress(messages) == messages

    async def test_compress_fallback_on_empty_summary(self, session, tools, mock_db):
        from raven.core.llm import LLMResponse

        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=LLMResponse(content="", finish_reason="stop"))
        config = AgentConfig(max_tool_rounds=3, use_memory=False)
        agent = Agent(session=session, tools=tools, db=mock_db, llm=llm, config=config)
        messages = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
        compressed = await agent._compress(messages)
        assert compressed[0] == messages[0]
        assert compressed[-8:] == messages[-8:]
        assert len(compressed) == 9

    async def test_compress_uses_summary(self, session, tools, mock_db):
        from raven.core.llm import LLMResponse

        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=LLMResponse(content="Key points summary", finish_reason="stop"))
        config = AgentConfig(max_tool_rounds=3, use_memory=False)
        agent = Agent(session=session, tools=tools, db=mock_db, llm=llm, config=config)
        messages = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
        compressed = await agent._compress(messages)
        assert any("[Context summary: Key points summary]" in m.get("content", "") for m in compressed)
        assert compressed[-4:] == messages[-4:]

    async def test_compress_llm_failure_falls_back(self, session, tools, mock_db):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("provider down"))
        config = AgentConfig(max_tool_rounds=3, use_memory=False)
        agent = Agent(session=session, tools=tools, db=mock_db, llm=llm, config=config)
        messages = [{"role": "user", "content": f"msg-{i}"} for i in range(12)]
        compressed = await agent._compress(messages)
        assert compressed[0] == messages[0]
        assert compressed[-8:] == messages[-8:]


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
