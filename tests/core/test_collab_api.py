from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.collab_api import create_collab_router


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
    with patch("raven.core.collab_api._get_manager", return_value=mock_manager):
        with patch("raven.core.collab_api._get_ws_manager", return_value=mock_ws_manager):
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
        resp = client.post("/api/collab/sessions/sess-1/join", json={
            "session_id": "sess-1", "user_id": "u1", "user_name": "Alice"
        })
        assert resp.status_code == 200
        mock_session.add_user.assert_called_once_with("u1", "Alice")

    def test_join_not_found(self, client, mock_manager):
        mock_manager.get_session.return_value = None
        resp = client.post("/api/collab/sessions/missing/join", json={
            "session_id": "missing", "user_id": "u1", "user_name": "Alice"
        })
        assert resp.status_code == 404

    def test_leave_session(self, client, mock_session):
        resp = client.post("/api/collab/sessions/sess-1/leave", json={
            "session_id": "sess-1", "user_id": "u1"
        })
        assert resp.status_code == 200
        mock_session.remove_user.assert_called_once_with("u1")


class TestCollabChanges:
    def test_apply_change(self, client, mock_session):
        resp = client.post("/api/collab/sessions/sess-1/changes", json={
            "session_id": "sess-1",
            "user_id": "u1",
            "file": "/test.py",
            "start_line": 0,
            "start_col": 0,
            "end_line": 0,
            "end_col": 5,
            "old_text": "hello",
            "new_text": "world",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_apply_change_failed(self, client, mock_session):
        mock_session.apply_change.return_value = False
        resp = client.post("/api/collab/sessions/sess-1/changes", json={
            "session_id": "sess-1",
            "user_id": "u1",
            "file": "/test.py",
            "start_line": 0,
            "start_col": 0,
            "end_line": 0,
            "end_col": 0,
            "old_text": "",
            "new_text": "x",
        })
        assert resp.status_code == 400

    def test_add_comment(self, client):
        resp = client.post("/api/collab/sessions/sess-1/comments", json={
            "session_id": "sess-1",
            "user_id": "u1",
            "file": "/test.py",
            "line": 5,
            "text": "looks good",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_get_content(self, client, mock_session):
        resp = client.get("/api/collab/sessions/sess-1/content")
        assert resp.status_code == 200
        assert resp.json()["content"] == "hello"
