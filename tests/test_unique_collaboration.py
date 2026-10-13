from __future__ import annotations

from typing import Any

import pytest

from raven.unique import collaboration as collab
from raven.unique.collaboration import (
    CollaborationManager,
    CollaborationSession,
    Comment,
    RealTimeCollaboration,
    SessionNotification,
    TextChange,
    WebSocketManager,
)


class _FakeWS:
    def __init__(self, fail: bool = False, fail_close: bool = False) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._fail = fail
        self._fail_close = fail_close

    async def send_text(self, message: str) -> None:
        if self._fail:
            msg = "send failed"
            raise RuntimeError(msg)
        self.sent.append(message)

    async def close(self) -> None:
        if self._fail_close:
            msg = "close failed"
            raise RuntimeError(msg)
        self.closed = True


class _FakeYText:
    def __init__(self) -> None:
        self._s = ""
        self.raise_on_delete = False

    def __str__(self) -> str:
        return self._s

    def insert(self, offset: int, text: str) -> None:
        self._s = self._s[:offset] + text + self._s[offset:]

    def delete(self, offset: int, length: int) -> None:
        if self.raise_on_delete:
            msg = "ytext delete failed"
            raise RuntimeError(msg)
        self._s = self._s[:offset] + self._s[offset + length :]

    def observe(self, callback: Any) -> None:
        self._callback = callback


class _FakeYDoc:
    def __init__(self) -> None:
        self._t = _FakeYText()
        self.raise_on_diff = False

    def get_text(self, name: str) -> _FakeYText:
        return self._t

    def encode_state_vector(self) -> bytes:
        return b"state-vector"

    def apply(self, update: bytes) -> None:
        if update == b"bad":
            msg = "apply failed"
            raise RuntimeError(msg)

    def encode_diff(self, state_vector: bytes) -> bytes:
        if self.raise_on_diff:
            msg = "diff failed"
            raise RuntimeError(msg)
        return b"diff-bytes"



class TestCollaborationSession:
    def setup_method(self) -> None:
        self.session = CollaborationSession("s1", "test.py")

    def test_add_user(self):
        self.session.add_user("u1", "Alice")
        assert len(self.session.users) == 1

    def test_remove_user(self):
        self.session.add_user("u1", "Alice")
        self.session.remove_user("u1")
        assert "u1" not in self.session.users

    def test_update_cursor(self):
        self.session.add_user("u1", "Alice")
        cursor = self.session.update_cursor("u1", "test.py", 10, 5)
        assert cursor.line == 10
        assert cursor.column == 5

    def test_apply_change_same_line(self):
        self.session.document.content = "hello world"
        change = TextChange(user_id="u1", file="test.py",
                            start_line=0, start_col=6, end_line=0, end_col=11,
                            old_text="world", new_text="there")
        result = self.session.apply_change(change)
        assert result is True
        assert self.session.document.content == "hello there"
        assert self.session.document.change_count == 1

    def test_change_history_bounded(self):
        from raven.unique.collaboration import _MAX_CHANGE_HISTORY

        self.session.document.content = "x"
        for _i in range(_MAX_CHANGE_HISTORY + 50):
            change = TextChange(user_id="u1", file="test.py",
                                start_line=0, start_col=0, end_line=0, end_col=1,
                                old_text="x", new_text="x")
            assert self.session.apply_change(change) is True
        assert len(self.session.document.changes) == _MAX_CHANGE_HISTORY
        assert self.session.document.change_count == _MAX_CHANGE_HISTORY + 50
        state = self.session.get_state()
        assert state["changes"] == _MAX_CHANGE_HISTORY + 50

    def test_apply_change_multiline(self):
        self.session.document.content = "line1\nline2\nline3"
        change = TextChange(user_id="u1", file="test.py",
                            start_line=0, start_col=0, end_line=2, end_col=5,
                            old_text="line1\nline2\nline3", new_text="replacement")
        result = self.session.apply_change(change)
        assert result is True
        assert self.session.document.content == "replacement"

    def test_add_comment(self):
        comment = self.session.add_comment("u1", "test.py", 5, "fix this")
        assert comment.text == "fix this"
        assert comment.line == 5

    def test_add_reply(self):
        parent = self.session.add_comment("u1", "test.py", 5, "fix this")
        reply = self.session.add_reply(parent.id, "u2", "done")
        assert reply is not None
        assert reply.text == "done"

    def test_add_reply_nonexistent(self):
        reply = self.session.add_reply("nonexistent", "u2", "done")
        assert reply is None

    def test_resolve_comment(self):
        comment = self.session.add_comment("u1", "test.py", 5, "fix this")
        assert self.session.resolve_comment(comment.id) is True
        assert self.session.resolve_comment("nonexistent") is False

    def test_get_cursors(self):
        self.session.add_user("u1", "Alice")
        self.session.update_cursor("u1", "test.py", 1, 1)
        cursors = self.session.get_cursors()
        assert len(cursors) == 1

    def test_get_comments_filtered(self):
        c1 = self.session.add_comment("u1", "test.py", 1, "first")
        self.session.add_comment("u1", "test.py", 2, "second")
        self.session.resolve_comment(c1.id)
        unresolved = self.session.get_comments(resolved=False)
        resolved = self.session.get_comments(resolved=True)
        assert len(unresolved) == 1
        assert len(resolved) == 1

    def test_get_user_list(self):
        self.session.add_user("u1", "Alice")
        self.session.add_user("u2", "Bob")
        users = self.session.get_user_list()
        assert len(users) == 2

    def test_get_state(self):
        self.session.add_user("u1", "Alice")
        state = self.session.get_state()
        assert state["session_id"] == "s1"
        assert state["users"] == 1


class TestCollaborationManager:
    def setup_method(self) -> None:
        self.manager = CollaborationManager()

    def test_create_session(self):
        session = self.manager.create_session("s1", "test.py")
        assert session is not None
        assert session.file_path == "test.py"

    def test_get_session(self):
        self.manager.create_session("s1", "test.py")
        assert self.manager.get_session("s1") is not None
        assert self.manager.get_session("nonexistent") is None

    def test_remove_session(self):
        self.manager.create_session("s1", "test.py")
        assert self.manager.remove_session("s1") is True
        assert self.manager.remove_session("s1") is False

    def test_list_sessions(self):
        self.manager.create_session("s1", "a.py")
        self.manager.create_session("s2", "b.py")
        sessions = self.manager.list_sessions()
        assert len(sessions) == 2

    def test_list_active_users(self):
        s1 = self.manager.create_session("s1", "a.py")
        s2 = self.manager.create_session("s2", "b.py")
        s1.add_user("u1", "Alice")
        s2.add_user("u2", "Bob")
        users = self.manager.list_active_users()
        assert len(users) == 2


class TestCollabApiDelete:
    def test_delete_session_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import raven.core.collab_api as collab_api

        app = FastAPI()
        app.include_router(collab_api.create_collab_router())
        client = TestClient(app)

        resp = client.post("/api/collab/sessions", json={"session_id": "del1", "file_path": "a.py"})
        assert resp.status_code == 200

        resp = client.delete("/api/collab/sessions/del1")
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        assert collab_api._get_manager().get_session("del1") is None

        resp = client.delete("/api/collab/sessions/del1")
        assert resp.status_code == 404


class TestSessionExtraBranches:
    def test_invalid_start_line(self):
        s = CollaborationSession("s1", "a.py")
        s.document.content = "only"
        ch = TextChange(user_id="u1", file="a.py", start_line=3, start_col=0, end_line=3, end_col=0, old_text="", new_text="x")
        assert s.apply_change(ch) is False

    def test_invalid_end_line(self):
        s = CollaborationSession("s1", "a.py")
        s.document.content = "only"
        ch = TextChange(user_id="u1", file="a.py", start_line=0, start_col=0, end_line=5, end_col=0, old_text="", new_text="x")
        assert s.apply_change(ch) is False

    def test_multiline_insert(self):
        s = CollaborationSession("s1", "a.py")
        s.document.content = "A\nB\nC"
        ch = TextChange(
            user_id="u1", file="a.py", start_line=0, start_col=0, end_line=2, end_col=1,
            old_text="A\nB\nC", new_text="X\nY\nZ",
        )
        assert s.apply_change(ch) is True
        assert s.document.version == 1

    def test_add_user_twice_and_user_info(self):
        s = CollaborationSession("s1", "a.py")
        s.add_user("u1", "Alice")
        s.add_user("u1", "Alice Again")
        info = s.get_user_info_list()
        assert info[0]["user_id"] == "u1"
        assert info[0]["connected"] is True

    def test_get_comments_none_branch(self):
        s = CollaborationSession("s1", "a.py")
        s.add_comment("u1", "a.py", 1, "x")
        assert s.get_comments() == s.comments

    def test_find_nested_reply(self):
        s = CollaborationSession("s1", "a.py")
        parent = s.add_comment("u1", "a.py", 1, "p")
        reply = s.add_reply(parent.id, "u2", "r")
        assert reply is not None
        assert s._find_comment(reply.id) is reply


class TestNotifications:
    async def test_poll_empty_times_out(self):
        s = CollaborationSession("s1", "a.py")
        assert await s.poll_notifications() is None

    async def test_notify_then_poll(self):
        s = CollaborationSession("s1", "a.py")
        await s.notify(SessionNotification(kind="x", session_id="s1", payload={}))
        note = await s.poll_notifications()
        assert note is not None
        assert note.kind == "x"


class TestWebSocketManager:
    async def test_connect_broadcasts_to_peers(self):
        mgr = WebSocketManager()
        ws1, ws2 = _FakeWS(), _FakeWS()
        await mgr.connect("s1", "u1", ws1)
        await mgr.connect("s1", "u2", ws2)
        assert mgr.connection_count("s1") == 2
        assert ws1.sent
        assert ws2.sent == []

    async def test_disconnect_removes_and_prunes(self):
        mgr = WebSocketManager()
        ws = _FakeWS()
        await mgr.connect("s1", "u1", ws)
        await mgr.disconnect("s1", "u1", ws)
        assert mgr.connection_count("s1") == 0
        assert "s1" not in mgr.active_sessions()
        assert "u1" not in mgr._user_connections

    async def test_broadcast_skips_exclude_and_drops_failing(self):
        mgr = WebSocketManager()
        good, bad = _FakeWS(), _FakeWS(fail=True)
        await mgr.connect("s1", "u1", good)
        await mgr.connect("s1", "u2", bad)
        good.sent.clear()
        await mgr.broadcast("s1", "hello", exclude=good)
        assert good.sent == []
        assert mgr.connection_count("s1") == 1

    async def test_broadcast_to_user(self):
        mgr = WebSocketManager()
        good, bad = _FakeWS(), _FakeWS(fail=True)
        await mgr.connect("s1", "u1", good)
        await mgr.connect("s2", "u1", bad)
        good.sent.clear()
        await mgr.broadcast_to_user("u1", {"k": "v"})
        assert good.sent
        assert len(mgr._user_connections["u1"]) == 1

    async def test_disconnect_all_closes(self):
        mgr = WebSocketManager()
        ws = _FakeWS()
        await mgr.connect("s1", "u1", ws)
        await mgr.disconnect_all("s1")
        assert ws.closed is True
        assert "s1" not in mgr._connections

    async def test_disconnect_all_close_error(self):
        mgr = WebSocketManager()
        ws = _FakeWS(fail_close=True)
        await mgr.connect("s1", "u1", ws)
        await mgr.disconnect_all("s1")
        assert "s1" not in mgr._connections


class TestFallbackCrdtApi:
    def test_crdt_api_without_ydoc(self):
        s = CollaborationSession("s1", "a.py")
        assert s.get_crdt_state_vector() is None
        assert s.apply_crdt_update(b"x") is False
        assert s.encode_crdt_diff(b"x") is None
        s.document.content = "abc"
        assert s.get_crdt_content() == "abc"
        s.set_crdt_content("z")
        assert s.document.content == "z"


class TestCrdtWithFakeYpy:
    def _mk(self, monkeypatch: pytest.MonkeyPatch) -> CollaborationSession:
        monkeypatch.setattr(collab, "HAS_YPY", True)
        monkeypatch.setattr(collab, "YDoc", _FakeYDoc, raising=False)
        return CollaborationSession("s1", "a.py")

    def test_init_registers_ydoc(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        assert s._ydoc is not None
        assert s.get_state()["crdt_enabled"] is True
        s._on_ytext_change([], False)

    def test_set_and_apply_change(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        s.set_crdt_content("hello\nworld")
        s.set_crdt_content("abc")
        ch = TextChange(
            user_id="u1", file="a.py", start_line=0, start_col=0, end_line=0, end_col=3,
            old_text="abc", new_text="ABC",
        )
        assert s.apply_change(ch) is True
        assert s.get_crdt_content() == "ABC"
        assert s.document.version == 1

    def test_apply_change_second_line(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        s.set_crdt_content("aaa\nbbb")
        ch = TextChange(
            user_id="u1", file="a.py", start_line=1, start_col=0, end_line=1, end_col=3,
            old_text="bbb", new_text="ccc",
        )
        assert s.apply_change(ch) is True
        assert s.get_crdt_content() == "aaa\nccc"

    def test_apply_invalid_bounds(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        s.set_crdt_content("only")
        bad_start = TextChange(user_id="u1", file="a.py", start_line=5, start_col=0, end_line=5, end_col=0, old_text="", new_text="x")
        assert s.apply_change(bad_start) is False
        bad_end = TextChange(user_id="u1", file="a.py", start_line=0, start_col=0, end_line=9, end_col=0, old_text="", new_text="x")
        assert s.apply_change(bad_end) is False

    def test_apply_error_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        s.set_crdt_content("hello")
        s._ytext.raise_on_delete = True
        ch = TextChange(
            user_id="u1", file="a.py", start_line=0, start_col=0, end_line=0, end_col=5,
            old_text="hello", new_text="HI",
        )
        assert s.apply_change(ch) is True
        assert s.document.content == "HI"

    def test_state_vector_and_diff(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        assert s.get_crdt_state_vector() == b"state-vector"
        assert s.encode_crdt_diff(b"x") == b"diff-bytes"
        assert s.apply_crdt_update(b"good") is True
        assert s.apply_crdt_update(b"bad") is False

    def test_encode_diff_error(self, monkeypatch: pytest.MonkeyPatch):
        s = self._mk(monkeypatch)
        s._ydoc.raise_on_diff = True
        assert s.encode_crdt_diff(b"x") is None


class TestRealTimeCollaboration:
    async def test_edit_without_session(self):
        rtc = RealTimeCollaboration()
        assert await rtc.edit("u1", []) is False

    async def test_edit_no_session_for_manager(self, monkeypatch: pytest.MonkeyPatch):
        rtc = RealTimeCollaboration()
        assert rtc.get_manager() is rtc._manager
        s = rtc.create_session("s1", "a.py")
        s.document.content = "hello"
        s.add_user("u1", "Alice")
        monkeypatch.setattr(rtc._manager, "get_session", lambda sid: None)
        ch = TextChange(user_id="u1", file="a.py", start_line=0, start_col=0, end_line=0, end_col=0, old_text="", new_text="x")
        assert await rtc.edit("u1", [ch]) is False

    async def test_full_join_edit_leave_flow(self, monkeypatch: pytest.MonkeyPatch):
        rtc = RealTimeCollaboration()
        s = rtc.create_session("s1", "a.py")
        s.document.content = "hello world"
        session = await rtc.join_session("s1", "u1", "Alice")
        assert session is not None
        ws = _FakeWS()
        await rtc.get_ws_manager().connect("s1", "u9", ws)
        ch = TextChange(
            user_id="ignored", file="a.py", start_line=0, start_col=0, end_line=0, end_col=5,
            old_text="hello", new_text="HELLO",
        )
        assert await rtc.edit("u1", [ch]) is True
        assert s.document.content == "HELLO world"
        assert any("text_change" in m for m in ws.sent)
        assert await rtc.leave_session("s1", "u1") is True

    async def test_edit_change_failure(self):
        rtc = RealTimeCollaboration()
        s = rtc.create_session("s1", "a.py")
        s.document.content = "one\nline"
        await rtc.join_session("s1", "u1", "Alice")
        bad = TextChange(user_id="u1", file="a.py", start_line=9, start_col=0, end_line=9, end_col=0, old_text="", new_text="x")
        assert await rtc.edit("u1", [bad]) is False

    async def test_join_missing_session(self):
        rtc = RealTimeCollaboration()
        assert await rtc.join_session("nope", "u1", "Alice") is None

    async def test_leave_missing_session(self):
        rtc = RealTimeCollaboration()
        assert await rtc.leave_session("nope", "u1") is False

    async def test_apply_change(self):
        rtc = RealTimeCollaboration()
        s = rtc.create_session("s1", "a.py")
        s.document.content = "abc"
        ch = TextChange(user_id="u1", file="a.py", start_line=0, start_col=0, end_line=0, end_col=1, old_text="a", new_text="X")
        assert await rtc.apply_change("s1", ch) is True
        assert await rtc.apply_change("missing", ch) is False

    async def test_update_cursor(self):
        rtc = RealTimeCollaboration()
        rtc.create_session("s1", "a.py")
        pos = await rtc.update_cursor("s1", "u1", "a.py", 3, 2)
        assert pos is not None and pos.line == 3
        assert await rtc.update_cursor("missing", "u1", "a.py", 1, 1) is None

    async def test_add_comment_and_reply(self):
        rtc = RealTimeCollaboration()
        rtc.create_session("s1", "a.py")
        c = await rtc.add_comment("s1", "u1", "a.py", 2, "hi")
        assert c is not None
        assert await rtc.add_comment("missing", "u1", "a.py", 1, "x") is None
        assert await rtc.add_reply("s1", c.id, "u2", "yo") is not None
        assert await rtc.add_reply("missing", c.id, "u2", "x") is None
        assert await rtc.add_reply("s1", "badparent", "u2", "x") is None

    async def test_resolve_comment(self):
        rtc = RealTimeCollaboration()
        rtc.create_session("s1", "a.py")
        c = await rtc.add_comment("s1", "u1", "a.py", 2, "hi")
        assert c is not None
        assert await rtc.resolve_comment("s1", c.id) is True
        assert await rtc.resolve_comment("missing", c.id) is False
        assert await rtc.resolve_comment("s1", "nonexistent") is False

    async def test_summary_and_listings(self):
        rtc = RealTimeCollaboration()
        s = rtc.create_session("s1", "a.py")
        s.document.content = "abc"
        await rtc.join_session("s1", "u1", "Alice")
        await rtc.update_cursor("s1", "u1", "a.py", 1, 1)
        c = await rtc.add_comment("s1", "u1", "a.py", 1, "comment text")
        assert c is not None
        await rtc.add_reply("s1", c.id, "u2", "reply")
        summary = rtc.get_session_summary("s1")
        assert summary is not None
        assert summary["cursors"] and summary["comments"] and summary["users"]
        assert rtc.get_session_summary("missing") is None
        assert rtc.get_active_sessions() == rtc.list_sessions()
        assert rtc.get_session("s1") is s
        assert rtc.remove_session("s1") is True

    def test_sync_crdt_state_without_ydoc(self):
        rtc = RealTimeCollaboration()
        rtc.create_session("s1", "a.py")
        assert rtc.sync_crdt_state("s1") is None
        assert rtc.sync_crdt_state("missing") is None

    def test_sync_crdt_state_with_ydoc(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(collab, "HAS_YPY", True)
        monkeypatch.setattr(collab, "YDoc", _FakeYDoc, raising=False)
        rtc = RealTimeCollaboration()
        rtc.create_session("s1", "a.py")
        rtc.create_session("s2", "b.py")
        assert rtc.sync_crdt_state("s1") == b"diff-bytes"
        assert rtc.sync_crdt_state("missing") is None
        assert rtc.sync_crdt_state("s1", "s2") == b"diff-bytes"
