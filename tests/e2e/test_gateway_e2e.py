from __future__ import annotations

import pytest

from raven.core.models import IncomingMessage
from tests.e2e.conftest import MockChannel


@pytest.mark.e2e
class TestGatewayE2E:
    async def test_channel_registration(self, gateway):
        assert "mock" in gateway.channels
        assert isinstance(gateway.channels["mock"], MockChannel)

    async def test_handle_message_sends_response(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="hello",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert len(channel.sent_messages) > 0

    async def test_handle_status_command(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="/status",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert any("running" in m.content.lower() for m in channel.sent_messages)

    async def test_handle_new_command(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="/new",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert any("fresh" in m.content for m in channel.sent_messages)

    async def test_handle_help_command(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="/help",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert any("/status" in m.content for m in channel.sent_messages)

    async def test_handle_reset_command(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="/reset",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert any("reset" in m.content.lower() for m in channel.sent_messages)

    async def test_unknown_command_falls_through(self, gateway):
        event = IncomingMessage(
            channel="mock",
            user_id="user1",
            session_id="mock:user1:default",
            text="/nonexistent",
        )
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert len(channel.sent_messages) > 0

    async def test_multiple_messages(self, gateway):
        channel = gateway.channels["mock"]
        for i in range(3):
            event = IncomingMessage(
                channel="mock",
                user_id="user1",
                session_id="mock:user1:default",
                text=f"message {i}",
            )
            await gateway.handle_message(event)
        assert len(channel.sent_messages) >= 3

    async def test_channel_bridge_present(self, gateway):
        assert hasattr(gateway, "mcp")
        assert hasattr(gateway.mcp.channel_bridge, "_send_message")
        assert hasattr(gateway.mcp.channel_bridge, "_list_channels")
        assert hasattr(gateway.mcp.channel_bridge, "register_tools")

    async def test_guardian_present(self, gateway):
        assert hasattr(gateway, "_guardian")
        report = gateway._guardian.status_report()
        assert "mock" in report
