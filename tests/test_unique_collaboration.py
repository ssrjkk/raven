from __future__ import annotations

from raven.unique.collaboration import CollaborationManager, CollaborationSession, Comment, TextChange


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
