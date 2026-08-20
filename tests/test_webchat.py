from __future__ import annotations

import time
from datetime import UTC, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
        from raven.core.config import settings

        secret = settings.web_secret_key.get_secret_value() if settings.web_secret_key else ""
        client = TestClient(channel.app)
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        response = client.get("/api/sessions", headers=headers)
        assert response.status_code == 200

    def test_api_sessions_list_rejects_anonymous_when_secured(self, channel):
        from raven.core.config import settings

        if not settings.web_secret_key:
            pytest.skip("web_secret_key not set")
        client = TestClient(channel.app)
        response = client.get("/api/sessions")
        assert response.status_code == 401

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
        from raven.core.config import settings

        secret = settings.web_secret_key.get_secret_value() if settings.web_secret_key else ""
        client = TestClient(channel.app)
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        response = client.get("/api/messages/test_sid", headers=headers)
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


class TestCanvasLinkProxy:
    def _proxied_content(self, channel, url, headers, content=b"<html>ok</html>"):
        with patch(
            "raven.core.security.ssrf.safe_fetch_async",
            AsyncMock(return_value=httpx.Response(200, headers=headers, content=content)),
        ):
            return TestClient(channel.app).get("/api/canvas/link", params={"url": url})

    def test_html_content_is_sandboxed(self, channel):
        response = self._proxied_content(
            channel, "https://example.com/page", {"content-type": "text/html; charset=utf-8"}
        )
        assert response.status_code == 200
        assert response.content == b"<html>ok</html>"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == "sandbox"

    def test_non_html_content_has_no_csp(self, channel):
        response = self._proxied_content(
            channel, "https://example.com/doc.pdf", {"content-type": "application/pdf"}, content=b"%PDF"
        )
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" not in response.headers

    def test_bad_scheme_rejected(self, channel):
        response = TestClient(channel.app).get("/api/canvas/link", params={"url": "javascript:alert(1)"})
        assert response.status_code == 400
        assert response.json()["error"] == "Invalid URL scheme"

    def test_proxy_failure_returns_502(self, channel):
        with patch(
            "raven.core.security.ssrf.safe_fetch_async",
            AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = TestClient(channel.app).get("/api/canvas/link", params={"url": "https://example.com/x"})
        assert response.status_code == 502
        assert response.json()["error"] == "Proxy failed"


class TestWebSocketEndpoints:
    @staticmethod
    def _ws_token() -> str:
        from raven.core.config import settings

        return settings.web_secret_key.get_secret_value()

    @staticmethod
    def _wait_handler_called(handler: AsyncMock, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while handler.await_count < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        handler.assert_awaited_once()

    def test_invalid_json_keeps_connection_alive(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws?token={self._ws_token()}") as ws:
            first = ws.receive_json()
            assert first["type"] == "session"
            assert first["session_id"].startswith("webchat:")
            ws.send_text("this is not json")
            error = ws.receive_json()
            assert error["type"] == "error"
            ws.send_text('{"text": "hello"}')
            self._wait_handler_called(handler)
            assert handler.await_args is not None
            event = handler.await_args.args[0]
            assert event.text == "hello"

    def test_ws_announces_session_id(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws?token={self._ws_token()}") as ws:
            first = ws.receive_json()
            assert first["type"] == "session"
            assert first["session_id"].startswith("webchat:")
            ws.send_text('{"text": "hi"}')
            self._wait_handler_called(handler)

    def test_foreign_session_id_is_ignored(self, channel):
        handler = AsyncMock()
        channel._handler = handler
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws?token={self._ws_token()}") as ws:
            first = ws.receive_json()
            assert first["type"] == "session"
            ws.send_text('{"text": "hi", "session_id": "webchat:attacker_client:default"}')
            self._wait_handler_called(handler)
            assert handler.await_args is not None
            event = handler.await_args.args[0]
            assert event.session_id.startswith("webchat:")
            assert "attacker_client" not in event.session_id

    def test_stream_invalid_json_keeps_connection_alive(self, channel):
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws/stream?token={self._ws_token()}") as ws:
            ws.send_text("not json")
            error = ws.receive_json()
            assert error["type"] == "error"

    def test_canvas_invalid_json_keeps_connection_alive(self, channel):
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws/canvas?token={self._ws_token()}") as ws:
            ws.send_text("not json")
            error = ws.receive_json()
            assert error["type"] == "error"

    def test_canvas_update_props_requires_component_id(self, channel):
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws/canvas?token={self._ws_token()}") as ws:
            ws.send_text('{"action": "update_props", "props": {"x": 1}}')
            error = ws.receive_json()
            assert error["type"] == "error"
