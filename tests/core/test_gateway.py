from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from raven.core.db import Database
from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage
from raven.core.plugin_loader import PluginLoader


@pytest.fixture
def mock_db():
    db = AsyncMock(spec=Database)
    db.db_path = ":memory:"
    db.connect = AsyncMock()
    db.disconnect = AsyncMock()
    db.find_or_create_user = AsyncMock(
        return_value={
            "id": "telegram:u1",
            "channel": "telegram",
            "external_id": "u1",
            "is_allowed": 1,
            "pairing_code": None,
        }
    )
    db.get_or_create_session = AsyncMock()
    db.save_message = AsyncMock()
    return db


@pytest.fixture
def plugin_loader():
    return PluginLoader()


@pytest.fixture
def gateway(mock_db, plugin_loader):
    g = Gateway(db=mock_db, plugin_loader=plugin_loader)
    g.registry.setup_defaults()
    return g


class TestGateway:
    async def test_gateway_init(self, gateway):
        assert gateway.db is not None
        assert gateway.llm is not None
        assert gateway.plugin_loader is not None
        assert gateway.channels.list_ids() == []

    async def test_register_channel(self, gateway):
        channel = AsyncMock()
        channel.channel_id = "test"
        gateway.register_channel(channel)
        assert gateway.channels.get("test") is not None

    async def test_start_stop(self, gateway):
        await gateway.start()
        assert gateway._running is True
        await gateway.stop()
        assert gateway._running is False

    async def test_handle_message_allowed(self, gateway):
        channel = AsyncMock()
        channel.channel_id = "test"
        gateway.register_channel(channel)

        event = IncomingMessage(channel="test", user_id="u1", text="hello")
        await gateway.handle_message(event)
        assert gateway.db.find_or_create_user.called

    async def test_handle_message_closed_policy(self, gateway):
        gateway.db.find_or_create_user = AsyncMock(
            return_value={"id": "test:u1", "channel": "test", "external_id": "u1", "is_allowed": 0}
        )
        channel = AsyncMock()
        channel.channel_id = "test"
        gateway.register_channel(channel)

        with patch("raven.core.gateway.gateway.settings") as mock_settings:
            mock_settings.dm_policy = "closed"
            event = IncomingMessage(channel="test", user_id="u1", text="hello")
            await gateway.handle_message(event)
            channel.send.assert_called_once()

    async def test_handle_message_pairing(self, gateway):
        gateway.db.find_or_create_user = AsyncMock(
            return_value={"id": "test:u1", "channel": "test", "external_id": "u1", "is_allowed": 0}
        )
        channel = AsyncMock()
        channel.channel_id = "test"
        gateway.register_channel(channel)

        with patch("raven.core.gateway.gateway.settings") as mock_settings:
            mock_settings.dm_policy = "pairing"
            event = IncomingMessage(channel="test", user_id="u1", text="hello")
            await gateway.handle_message(event)
            channel.send.assert_called_once()
