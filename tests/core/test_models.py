from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from raven.core.models import IncomingMessage, Message, PluginTool, Session


class TestMessage:
    def test_create_message(self):
        msg = Message(session_id="s1", role="user", content="hello")
        assert msg.session_id == "s1"
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.id is not None
        assert isinstance(msg.created_at, datetime)

    def test_message_defaults(self):
        msg = Message(session_id="s1", role="user", content="test")
        assert msg.metadata == {}
        assert msg.channel == ""

    def test_message_invalid_role(self):
        with pytest.raises(ValidationError):
            Message(session_id="s1", role="invalid", content="x")

    def test_message_to_dict(self):
        msg = Message(session_id="s1", role="user", content="hello")
        d = msg.to_dict()
        assert d["session_id"] == "s1"
        assert d["role"] == "user"
        assert d["content"] == "hello"
        assert isinstance(d["created_at"], str)

    def test_tool_message(self):
        msg = Message(session_id="s1", role="tool", content='{"result": "ok"}')
        assert msg.role == "tool"


class TestSession:
    def test_create_session(self):
        s = Session(id="s1", channel="telegram", user_id="user1")
        assert s.id == "s1"
        assert s.channel == "telegram"
        assert s.user_id == "user1"
        assert s.agent_id == "default"
        assert s.system_prompt is None

    def test_session_with_optional(self):
        s = Session(id="s1", channel="discord", user_id="u1", agent_id="coder", system_prompt="Be helpful")
        assert s.agent_id == "coder"
        assert s.system_prompt == "Be helpful"

    def test_session_dates(self):
        s = Session(id="s1", channel="telegram", user_id="u1")
        assert isinstance(s.created_at, datetime)
        assert isinstance(s.updated_at, datetime)


class TestPluginTool:
    def test_create_tool(self):
        async def dummy(param: str) -> str:
            return param

        tool = PluginTool(name="test", description="A test tool", parameters={"type": "object"}, handler=dummy)
        assert tool.name == "test"
        assert tool.description == "A test tool"


class TestIncomingMessage:
    def test_create(self):
        msg = IncomingMessage(channel="telegram", user_id="u1", text="hello")
        assert msg.channel == "telegram"
        assert msg.user_id == "u1"
        assert msg.text == "hello"
        assert msg.session_id == ""

    def test_with_metadata(self):
        msg = IncomingMessage(channel="discord", user_id="u1", text="hi", metadata={"key": "val"})
        assert msg.metadata["key"] == "val"
