from __future__ import annotations

from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from raven.channels.webchat.channel import WebChatChannel
from raven.core.models import Message


class _FakeSession:
    def __init__(self):
        self.id = "test_sid"
        self.channel = "webchat"
        self.user_id = "web_user"
        self.agent_id = None
        self.updated_at = datetime.now(UTC)


@pytest.fixture
def db():
    mock_db = MagicMock()
    mock_db.get_sessions = AsyncMock(return_value=[])
    mock_db.get_or_create_session = AsyncMock(return_value=_FakeSession())
    mock_db.get_session_messages = AsyncMock(return_value=[])
    mock_db.delete_session = AsyncMock()
    return mock_db


@pytest.fixture
def channel(db):
    return WebChatChannel(db)


class TestWebChatChannel:
    def test_channel_id(self, channel):
        assert channel.channel_id == "webchat"

    @pytest.mark.asyncio
    async def test_start_stop(self, channel):
        await channel.start()
        channel._connections["test_client"] = AsyncMock()
        await channel.stop()
        assert len(channel._connections) == 0

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, channel):
        await channel.connect()
        await channel.disconnect()

    @pytest.mark.asyncio
    async def test_on_message(self, channel):
        handler = AsyncMock()
        await channel.on_message(handler)
        assert channel._handler is handler

    @pytest.mark.asyncio
    async def test_send_no_connection(self, channel):
        msg = Message(session_id="webchat:nonexistent", channel="webchat", role="assistant", content="hello")
        await channel.send("webchat:nonexistent", msg)

    @pytest.mark.asyncio
    async def test_send_with_connection(self, channel):
        mock_ws = AsyncMock()
        channel._connections["test_client"] = mock_ws
        msg = Message(session_id="webchat:test_client", channel="webchat", role="assistant", content="hello")
        await channel.send("webchat:test_client", msg)
        mock_ws.send_json.assert_awaited_once()

    def test_app_property(self, channel):
        app = channel.app
        assert app is not None

    def test_index_html(self):
        from raven.channels.webchat.channel import INDEX_HTML

        assert "Raven AI" in INDEX_HTML
        assert "alpinejs" in INDEX_HTML

    def test_api_sessions_list(self, channel):
        client = TestClient(channel.app)
        response = client.get("/api/sessions")
        assert response.status_code == 200

    def test_api_create_session(self, channel):
        client = TestClient(channel.app)
        response = client.post("/api/sessions")
        assert response.status_code == 200

    def test_api_delete_session(self, channel):
        client = TestClient(channel.app)
        response = client.delete("/api/sessions/test_sid")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_api_messages(self, channel):
        client = TestClient(channel.app)
        response = client.get("/api/messages/test_sid")
        assert response.status_code == 200
        assert response.json() == []

    def test_index_returns_html(self, channel):
        client = TestClient(channel.app)
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_health_check(self, channel):
        assert not await channel.health_check()
        channel._ready = True
        assert await channel.health_check()

    @pytest.mark.asyncio
    async def test_stop_no_connections(self, channel):
        await channel.start()
        await channel.stop()

    @pytest.mark.asyncio
    async def test_send_error_handling(self, channel):
        mock_ws = AsyncMock()
        mock_ws.send_json.side_effect = RuntimeError("WS crashed")
        channel._connections["client_x"] = mock_ws
        msg = Message(
            session_id="webchat:client_x:default", channel="webchat",
            role="assistant", content="Hello",
        )
        await channel.send("webchat:client_x:default", msg)
        mock_ws.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_invalid_session_format(self, channel):
        msg = Message(session_id="invalid", channel="webchat", role="assistant", content="Hello")
        await channel.send("invalid", msg)

    @pytest.mark.asyncio
    async def test_connect_sets_ready(self, channel):
        await channel.connect()
        assert channel._ready

    @pytest.mark.asyncio
    async def test_disconnect_closes_connections(self, channel):
        mock_ws = AsyncMock()
        channel._connections["c1"] = mock_ws
        await channel.disconnect()
        mock_ws.close.assert_awaited_once()
        assert len(channel._connections) == 0
