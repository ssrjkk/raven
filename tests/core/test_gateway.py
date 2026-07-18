from __future__ import annotations

import pytest

from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage
from tests.conftest import MockChannel


class TestGateway:
    async def test_gateway_init(self, gateway: Gateway):
        assert gateway.db is not None
        assert gateway.llm is not None
        assert gateway.plugin_loader is not None
        channels = await gateway.channels.list_ids()
        assert channels == ["mock"]

    async def test_register_channel(self, gateway: Gateway):
        channel = MockChannel()
        channel.channel_id = "test"
        await gateway.register_channel(channel)
        ch = await gateway.channels.get("test")
        assert ch is channel

    async def test_start_stop(self, gateway: Gateway):
        await gateway.start()
        assert gateway._running is True
        await gateway.stop()
        assert gateway._running is False

    async def test_handle_message_sends_response(self, gateway: Gateway):
        await gateway.start()
        event = IncomingMessage(channel="mock", user_id="u1", session_id="mock:u1", text="hello")
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        assert len(channel.sent_messages) > 0
        last = channel.sent_messages[-1]
        assert "Test response" in last.content

    async def test_closed_policy_blocks_user(self, gateway: Gateway, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "closed")
        await gateway.start()
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        event = IncomingMessage(channel="mock", user_id="blocked", session_id="mock:blocked", text="hello")
        await gateway.handle_message(event)
        assert len(channel.sent_messages) > 0
        last = channel.sent_messages[-1]
        assert "not authorized" in last.content.lower()
        await gateway.stop()

    async def test_pairing_policy_sends_code(self, gateway: Gateway, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "pairing")
        await gateway.start()
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        event = IncomingMessage(channel="mock", user_id="new_user", session_id="mock:new_user", text="hello")
        await gateway.handle_message(event)
        assert len(channel.sent_messages) > 0
        last = channel.sent_messages[-1]
        assert "pairing code" in last.content.lower()
        await gateway.stop()

    async def test_double_start_raises(self, gateway: Gateway):
        await gateway.start()
        with pytest.raises(RuntimeError, match="already running"):
            await gateway.start()
        await gateway.stop()

    async def test_double_stop_does_not_raise(self, gateway: Gateway):
        await gateway.start()
        await gateway.stop()
        await gateway.stop()

    async def test_dropped_when_not_running(self, gateway: Gateway):
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        event = IncomingMessage(channel="mock", user_id="u1", session_id="mock:u1", text="hello")
        await gateway.handle_message(event)
        assert len(channel.sent_messages) == 0
