from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from raven.core.collab_api import create_collab_router
from raven.core.config import settings


@pytest.fixture()
def mock_session():
    session = MagicMock()
    session.session_id = "sess-1"
    session.file_path = "/test.py"
    doc = MagicMock()
    doc.content = "hello"
    doc.version = 1
    session.document = doc
    session.add_user.return_value = None
    session.remove_user.return_value = None
    session.apply_change.return_value = True
    session.get_state.return_value = {"session_id": "sess-1", "file_path": "/test.py"}
    session.get_cursors.return_value = []
    session.get_comments.return_value = []
    session.get_user_list.return_value = []
    comment = MagicMock()
    comment.id = "c1"
    session.add_comment.return_value = comment
    return session


@pytest.fixture()
def mock_manager(mock_session):
    mgr = MagicMock()
    mgr.create_session.return_value = mock_session
    mgr.list_sessions.return_value = ["sess-1"]
    mgr.get_session.return_value = mock_session
    mgr.remove_session.return_value = True
    return mgr


@pytest.fixture()
def mock_ws_manager():
    wsm = AsyncMock()
    wsm.disconnect_all = AsyncMock()
    return wsm


@pytest.fixture()
def client(mock_manager, mock_ws_manager):
    with patch("raven.core.collab_api.get_manager", return_value=mock_manager):
        with patch("raven.core.collab_api.get_ws_manager", return_value=mock_ws_manager):
            router = create_collab_router()
            app = FastAPI()
            app.include_router(router)
            yield TestClient(app)


class TestCollabSessions:
    def test_create_session(self, client):
        resp = client.post("/api/collab/sessions", json={"session_id": "sess-1", "file_path": "/test.py"})
        assert resp.status_code == 200
        assert resp.json()["session_id"] == "sess-1"

    def test_list_sessions(self, client):
        resp = client.get("/api/collab/sessions")
        assert resp.status_code == 200
        assert "sessions" in resp.json()

    def test_get_session(self, client, mock_session):
        resp = client.get("/api/collab/sessions/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "hello"

    def test_get_session_not_found(self, client, mock_manager):
        mock_manager.get_session.return_value = None
        resp = client.get("/api/collab/sessions/missing")
        assert resp.status_code == 404

    def test_delete_session(self, client, mock_ws_manager):
        resp = client.delete("/api/collab/sessions/sess-1")
        assert resp.status_code == 200
        mock_ws_manager.disconnect_all.assert_called_once()

    def test_delete_session_not_found(self, client, mock_manager):
        mock_manager.remove_session.return_value = False
        resp = client.delete("/api/collab/sessions/missing")
        assert resp.status_code == 404


class TestCollabUsers:
    def test_join_session(self, client, mock_session):
        resp = client.post(
            "/api/collab/sessions/sess-1/join", json={"session_id": "sess-1", "user_id": "u1", "user_name": "Alice"}
        )
        assert resp.status_code == 200
        mock_session.add_user.assert_called_once_with("u1", "Alice")

    def test_join_not_found(self, client, mock_manager):
        mock_manager.get_session.return_value = None
        resp = client.post(
            "/api/collab/sessions/missing/join", json={"session_id": "missing", "user_id": "u1", "user_name": "Alice"}
        )
        assert resp.status_code == 404

    def test_leave_session(self, client, mock_session):
        resp = client.post("/api/collab/sessions/sess-1/leave", json={"session_id": "sess-1", "user_id": "u1"})
        assert resp.status_code == 200
        mock_session.remove_user.assert_called_once_with("u1")


class TestCollabChanges:
    def test_apply_change(self, client, mock_session):
        resp = client.post(
            "/api/collab/sessions/sess-1/changes",
            json={
                "session_id": "sess-1",
                "user_id": "u1",
                "file": "/test.py",
                "start_line": 0,
                "start_col": 0,
                "end_line": 0,
                "end_col": 5,
                "old_text": "hello",
                "new_text": "world",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_apply_change_failed(self, client, mock_session):
        mock_session.apply_change.return_value = False
        resp = client.post(
            "/api/collab/sessions/sess-1/changes",
            json={
                "session_id": "sess-1",
                "user_id": "u1",
                "file": "/test.py",
                "start_line": 0,
                "start_col": 0,
                "end_line": 0,
                "end_col": 0,
                "old_text": "",
                "new_text": "x",
            },
        )
        assert resp.status_code == 400

    def test_add_comment(self, client):
        resp = client.post(
            "/api/collab/sessions/sess-1/comments",
            json={
                "session_id": "sess-1",
                "user_id": "u1",
                "file": "/test.py",
                "line": 5,
                "text": "looks good",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_get_content(self, client, mock_session):
        resp = client.get("/api/collab/sessions/sess-1/content")
        assert resp.status_code == 200
        assert resp.json()["content"] == "hello"


class TestCollabWebSocket:
    """A collab socket opens for a credential, and the credential is what names the caller."""

    @pytest.fixture(autouse=True)
    def _operator_key(self, monkeypatch):
        monkeypatch.setattr(settings, "web_secret_key", SecretStr("operator-key-under-test"))

    def test_an_uncertified_socket_never_stays_open(self, client):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/collab/sessions/sess-1/ws") as ws:
                ws.receive_json()
        assert exc.value.code == 1008

    def test_an_empty_secret_does_not_open_it_either(self, client, monkeypatch):
        # The guard used to read `if _secure_mode() and not authenticated`, which made the whole
        # check look skippable. There is no mode in which an anonymous socket is let in.
        monkeypatch.setattr(settings, "web_secret_key", SecretStr(""))
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/collab/sessions/sess-1/ws") as ws:
                ws.receive_json()
        assert exc.value.code == 1008

    async def test_the_credential_names_the_caller_not_the_first_message(self, client, mock_ws_manager):
        from raven.core.auth.tokens import token_manager

        token = await token_manager.create_token("u7", "user")
        with client.websocket_connect(f"/api/collab/sessions/sess-1/ws?token={token}") as ws:
            # The claim is sent before anything is read: a handler that waits for it first would
            # deadlock here instead of failing, and a hanging test proves nothing.
            ws.send_json({"kind": "auth", "user_id": "whoever-i-claim"})
            assert ws.receive_json()["kind"] == "state"
        assert mock_ws_manager.connect.await_args.args[:2] == ("sess-1", "u7")


class TestCollabEditsReachEditors:
    """The console's session tab rendered one REST snapshot and never opened the socket the gateway
    mounts for the same session, so two editors each saw only their own last save.

    These run against the real stores. A mocked manager answers any frame shape you ask it to, which
    is precisely the claim that needed proving.
    """

    SESSION = "live-1"

    @pytest.fixture(autouse=True)
    def _real_stores(self, monkeypatch):
        from raven.core import collab_api
        from raven.unique.collaboration import CollaborationManager, WebSocketManager

        monkeypatch.setattr(collab_api, "_manager", CollaborationManager())
        monkeypatch.setattr(collab_api, "_ws_manager", WebSocketManager())
        monkeypatch.setattr(settings, "web_secret_key", SecretStr("operator-key-under-test"))

    @pytest.fixture()
    def live(self):
        app = FastAPI()
        app.include_router(create_collab_router())
        with TestClient(app) as client:
            client.post("/api/collab/sessions", json={"session_id": self.SESSION, "file_path": "a.py"})
            yield client

    def _socket(self, client: TestClient, session: str = SESSION):
        return client.websocket_connect(f"/api/collab/sessions/{session}/ws?token=operator-key-under-test")

    @staticmethod
    def _until(ws, kind: str, limit: int = 5) -> dict[str, Any]:
        """Read frames until `kind` arrives. The gateway also announces joins, so the wanted frame is
        rarely the first one -- and a limit keeps a missing frame a failure rather than a hang."""
        for _ in range(limit):
            frame: dict[str, Any] = ws.receive_json()
            if frame.get("kind") == kind:
                return frame
        pytest.fail(f"no {kind!r} frame in the first {limit} frames")

    def test_an_edit_by_one_editor_reaches_the_other(self, live):
        change = {
            "kind": "change",
            "file": "a.py",
            "start_line": 0,
            "start_col": 0,
            "end_line": 0,
            "end_col": 0,
            "old_text": "",
            "new_text": "alpha",
        }
        with self._socket(live) as first, self._socket(live) as second:
            self._until(first, "state")
            self._until(second, "state")
            first.send_json(change)
            assert self._until(first, "ack")["version"] == 1
            frame = self._until(second, "change")
        assert frame["new_text"] == "alpha"
        assert frame["version"] == 1
        assert frame["start_line"] == 0 and frame["end_col"] == 0

    def test_an_edit_made_over_http_reaches_the_live_socket(self, live):
        """REST and socket used to be two different stories about the same document: the HTTP path
        applied the change and told no socket, so an editor stayed on text a build step had replaced."""
        with self._socket(live) as ws:
            assert self._until(ws, "state")["version"] == 0
            resp = live.post(
                f"/api/collab/sessions/{self.SESSION}/changes",
                json={
                    "session_id": self.SESSION,
                    "user_id": "ci",
                    "file": "a.py",
                    "start_line": 0,
                    "start_col": 0,
                    "end_line": 0,
                    "end_col": 0,
                    "old_text": "",
                    "new_text": "beta",
                },
            )
            assert resp.status_code == 200
            frame = self._until(ws, "change")
        assert frame["new_text"] == "beta"
        assert frame["version"] == resp.json()["version"]

    def test_a_change_to_a_session_nobody_opened_is_answered_not_dropped(self, live):
        with self._socket(live, "not-created") as ws:
            ws.send_json(
                {
                    "kind": "change",
                    "file": "a.py",
                    "start_line": 0,
                    "start_col": 0,
                    "end_line": 0,
                    "end_col": 0,
                    "old_text": "",
                    "new_text": "x",
                }
            )
            assert "not open" in self._until(ws, "error")["content"]

    def test_a_frame_the_handler_does_not_know_is_answered(self, live):
        """A client that sends the wrong `kind` used to wait forever with a open socket and no reply."""
        with self._socket(live) as ws:
            self._until(ws, "state")
            ws.send_json({"kind": "typing"})
            assert "typing" in self._until(ws, "error")["content"]

    def test_a_session_the_agent_tool_creates_is_the_console_session(self, live):
        from raven.tools.collaboration import collab_create_session

        assert collab_create_session("from-tool", "b.py").startswith("Session 'from-tool' created")
        listed = {s["session_id"] for s in live.get("/api/collab/sessions").json()["sessions"]}
        assert "from-tool" in listed
