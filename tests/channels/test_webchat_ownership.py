"""A session belongs to the caller who made it, not to whoever holds any valid credential.

Measured before the fix: `POST /api/sessions` stamped every row it created with the literal
`"web_user"`, and `GET /api/sessions` and `GET /api/messages/{id}` answered out of the whole
`sessions`/`messages` tables for any authenticated caller. On an install with more than one login,
the second user to open the chat read the first one's history and could delete it.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from raven.channels.webchat.channel import WebChatChannel
from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.db import Database
from raven.core.models import Message, Session


class _StubDB:
    """The four session reads and two writes these routes make, kept in a dict.

    A real `Database` cannot stand in here: `TestClient` runs the app on its own event loop in a
    worker thread, and an aiosqlite connection belongs to the loop that opened it.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.messages: dict[str, list[Message]] = {}

    async def get_sessions(self, channel: str | None = None) -> list[Session]:
        rows = [s for s in self.sessions.values() if channel is None or s.channel == channel]
        return sorted(rows, key=lambda s: s.updated_at, reverse=True)

    async def get_or_create_session(
        self, session_id: str, channel: str, user_id: str, agent_id: str = "default"
    ) -> Session:
        existing = self.sessions.get(session_id)
        if existing is not None:
            return existing
        session = Session(id=session_id, channel=channel, user_id=user_id, agent_id=agent_id)
        self.sessions[session_id] = session
        return session

    async def get_session_owner(self, session_id: str) -> str | None:
        session = self.sessions.get(session_id)
        return session.user_id if session else None

    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[Message]:
        return self.messages.get(session_id, [])[:limit]

    async def delete_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)
        self.messages.pop(session_id, None)


@pytest.fixture
def db() -> _StubDB:
    return _StubDB()


@pytest.fixture
def client(db: _StubDB) -> TestClient:
    return TestClient(WebChatChannel(db).app)  # type: ignore[arg-type]


def _token_for(user_id: str, role: str = "user") -> str:
    return asyncio.run(token_manager.create_token(user_id, role))


def _bearer(user_id: str, role: str = "user") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(user_id, role)}"}


def _operator() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.web_secret_key.get_secret_value()}"}


def _create(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/sessions", headers=headers)
    assert response.status_code == 200
    return str(response.json()["id"])


def _seed(db: _StubDB, owner: str) -> str:
    """A session with history, filed the way `/ws` leaves the ones it writes."""
    session_id = f"webchat:{owner.rsplit(':', 1)[-1]}:default"
    db.sessions[session_id] = Session(id=session_id, channel="webchat", user_id=owner)
    db.messages[session_id] = [Message(id=f"m-{owner}", session_id=session_id, role="user", content="the note")]
    return session_id


@pytest.mark.skipif(not settings.web_secret_key, reason="web_secret_key not set")
class TestSessionOwnership:
    def test_a_created_session_is_stamped_with_the_caller(self, client, db):
        session_id = _create(client, _bearer("user:alice"))
        assert db.sessions[session_id].user_id == "user:alice"

    def test_two_callers_are_no_longer_the_same_person(self, client, db):
        """Both rows used to read `web_user`, so nothing could tell them apart."""
        _create(client, _bearer("user:alice"))
        _create(client, _bearer("user:bob"))
        assert {s.user_id for s in db.sessions.values()} == {"user:alice", "user:bob"}

    def test_the_list_only_answers_with_the_callers_own_sessions(self, client, db):
        alice = _seed(db, "user:alice")
        bob = _seed(db, "user:bob")
        rows = client.get("/api/sessions", headers=_bearer("user:alice")).json()
        assert [r["id"] for r in rows] == [alice]
        rows = client.get("/api/sessions", headers=_bearer("user:bob")).json()
        assert [r["id"] for r in rows] == [bob]

    def test_the_operator_still_sees_every_session(self, client, db):
        alice = _seed(db, "user:alice")
        bob = _seed(db, "user:bob")
        rows = client.get("/api/sessions", headers=_operator()).json()
        assert {r["id"] for r in rows} == {alice, bob}

    def test_a_session_made_with_the_shared_secret_belongs_to_the_operator(self, client, db):
        session_id = _create(client, _operator())
        assert db.sessions[session_id].user_id == "admin"
        assert [r["id"] for r in client.get("/api/sessions", headers=_operator()).json()] == [session_id]

    def test_another_users_history_is_not_readable(self, client, db):
        bob = _seed(db, "user:bob")
        assert client.get(f"/api/messages/{bob}", headers=_bearer("user:alice")).status_code == 404

    def test_the_owner_reads_their_own_history(self, client, db):
        alice = _seed(db, "user:alice")
        response = client.get(f"/api/messages/{alice}", headers=_bearer("user:alice"))
        assert response.status_code == 200
        assert [m["content"] for m in response.json()] == ["the note"]

    def test_the_operator_reads_any_history(self, client, db):
        bob = _seed(db, "user:bob")
        assert client.get(f"/api/messages/{bob}", headers=_operator()).status_code == 200

    def test_another_users_session_is_not_deletable(self, client, db):
        bob = _seed(db, "user:bob")
        assert client.delete(f"/api/sessions/{bob}", headers=_bearer("user:alice")).status_code == 404
        assert bob in db.sessions

    def test_the_owner_deletes_their_own_session(self, client, db):
        alice = _seed(db, "user:alice")
        assert client.delete(f"/api/sessions/{alice}", headers=_bearer("user:alice")).status_code == 200
        assert alice not in db.sessions

    def test_a_missing_session_is_refused_rather_than_reported_deleted(self, client, db):
        """Deleting nothing used to answer `{"ok": true}`."""
        response = client.delete("/api/sessions/webchat:never:default", headers=_bearer("user:alice"))
        assert response.status_code == 404

    def test_someone_elses_session_and_no_session_answer_identically(self, client, db):
        bob = _seed(db, "user:bob")
        foreign = client.delete(f"/api/sessions/{bob}", headers=_bearer("user:alice"))
        missing = client.delete("/api/sessions/webchat:never:default", headers=_bearer("user:alice"))
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/sessions"),
            ("post", "/api/sessions"),
            ("delete", "/api/sessions/webchat:anyone:default"),
            ("get", "/api/messages/webchat:anyone:default"),
        ],
    )
    def test_an_anonymous_caller_is_refused(self, client, db, method, path):
        assert getattr(client, method)(path).status_code == 401

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("get", "/api/sessions"),
            ("post", "/api/sessions"),
            ("delete", "/api/sessions/webchat:anyone:default"),
            ("get", "/api/messages/webchat:anyone:default"),
        ],
    )
    def test_a_credential_this_install_did_not_issue_is_refused(self, client, db, method, path):
        response = getattr(client, method)(path, headers={"Authorization": "Bearer not-a-token"})
        assert response.status_code == 401

    def test_a_viewer_does_not_get_the_operators_breadth(self, client, db):
        _seed(db, "user:alice")
        rows = client.get("/api/sessions", headers=_bearer("user:carol", role="viewer")).json()
        assert rows == []

    def test_a_session_another_channel_wrote_is_not_offered_or_deleted(self, client, db):
        """The list reads the one shared table, so it filters by owner rather than by channel."""
        telegram = "telegram:12345:default"
        db.sessions[telegram] = Session(id=telegram, channel="telegram", user_id="telegram:12345")
        assert client.get("/api/sessions", headers=_bearer("user:alice")).json() == []
        assert client.delete(f"/api/sessions/{telegram}", headers=_bearer("user:alice")).status_code == 404


class TestAnInstallWithNoSecret:
    """With no credential to check, the port is the boundary and the old breadth has to hold."""

    @pytest.fixture
    def open_client(self, monkeypatch, db: _StubDB) -> TestClient:
        monkeypatch.setattr(settings, "web_secret_key", None)
        return TestClient(WebChatChannel(db).app)  # type: ignore[arg-type]

    def test_an_anonymous_caller_is_still_answered(self, open_client, db):
        session_id = _create(open_client, {})
        assert open_client.get("/api/sessions").status_code == 200
        assert open_client.get(f"/api/messages/{session_id}").status_code == 200
        assert open_client.delete(f"/api/sessions/{session_id}").status_code == 200

    def test_the_caller_is_the_operator_so_the_whole_table_stays_visible(self, open_client, db):
        _seed(db, "user:alice")
        assert len(open_client.get("/api/sessions").json()) == 1


class TestWebSocketNamesTheSameCaller:
    def test_a_credential_means_the_same_person_on_both_entry_points(self, db):
        """`/ws` files its rows under the identity `GET /api/sessions` then filters by."""
        events = []

        async def _capture(event) -> None:
            events.append(event)

        channel = WebChatChannel(db)
        channel._handler = _capture
        client = TestClient(channel.app)
        with client.websocket_connect(f"/ws?token={_token_for('user:alice')}") as ws:
            assert ws.receive_json()["type"] == "session"
            ws.send_text('{"text": "hello"}')
            deadline = time.monotonic() + 2.0
            while not events and time.monotonic() < deadline:
                time.sleep(0.01)
        assert events[0].user_id == "user:alice"


@pytest.mark.asyncio
async def test_get_session_owner_reads_the_row_it_was_asked_for(tmp_path):
    """The one-line primitive the ownership checks rest on, against real SQLite."""
    db = Database(tmp_path / "raven.db")
    await db.connect()
    try:
        await db.get_or_create_session("webchat:abc:default", "webchat", "user:alice")
        assert await db.get_session_owner("webchat:abc:default") == "user:alice"
        assert await db.get_session_owner("webchat:nope:default") is None
    finally:
        await db.disconnect()
