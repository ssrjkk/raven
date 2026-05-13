from __future__ import annotations

import pytest

from raven.core.db import Database
from raven.core.models import Message


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.connect()
    yield d
    await d.disconnect()


class TestDatabase:
    async def test_connect_and_create_tables(self, db):
        async with db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as c:
            tables = {r[0] for r in await c.fetchall()}
        assert "sessions" in tables
        assert "messages" in tables
        assert "users" in tables
        assert "plugin_state" in tables

    async def test_get_or_create_session(self, db):
        session = await db.get_or_create_session("s1", "telegram", "user1")
        assert session.id == "s1"
        assert session.channel == "telegram"

        session2 = await db.get_or_create_session("s1", "telegram", "user1")
        assert session2.id == "s1"

    async def test_save_and_get_messages(self, db):
        await db.get_or_create_session("s1", "telegram", "user1")
        msg = Message(session_id="s1", channel="telegram", role="user", content="hello")
        await db.save_message(msg)

        msgs = await db.get_session_messages("s1")
        assert len(msgs) == 1
        assert msgs[0].content == "hello"
        assert msgs[0].role == "user"

    async def test_multiple_messages_order(self, db):
        await db.get_or_create_session("s1", "telegram", "user1")
        for i in range(5):
            msg = Message(session_id="s1", channel="telegram", role="user", content=f"msg{i}")
            await db.save_message(msg)

        msgs = await db.get_session_messages("s1", limit=3)
        assert len(msgs) == 3

    async def test_find_or_create_user(self, db):
        user = await db.find_or_create_user("telegram", "12345", "Test User")
        assert user["channel"] == "telegram"
        assert user["external_id"] == "12345"
        assert user["is_allowed"] == 0

        user2 = await db.find_or_create_user("telegram", "12345")
        assert user2["id"] == user["id"]

    async def test_user_pairing(self, db):
        user = await db.find_or_create_user("telegram", "u1")
        await db.set_pairing_code(user["id"], "ABC123")
        found = await db.get_user_by_pairing_code("ABC123")
        assert found is not None
        assert found["id"] == user["id"]

        await db.set_user_allowed(user["id"], True)
        pending = await db.get_pending_pairing_users()
        assert len(pending) == 0

    async def test_plugin_state(self, db):
        await db.save_plugin_state("memory", "key1", "value1")
        val = await db.get_plugin_state("memory", "key1")
        assert val == "value1"

        val2 = await db.get_plugin_state("memory", "nonexistent")
        assert val2 is None

    async def test_get_sessions(self, db):
        await db.get_or_create_session("s1", "telegram", "u1")
        await db.get_or_create_session("s2", "discord", "u2")
        all_s = await db.get_sessions()
        assert len(all_s) == 2

        tg_s = await db.get_sessions(channel="telegram")
        assert len(tg_s) == 1

    async def test_delete_session(self, db):
        await db.get_or_create_session("s1", "telegram", "u1")
        msg = Message(session_id="s1", channel="telegram", role="user", content="x")
        await db.save_message(msg)
        await db.delete_session("s1")
        msgs = await db.get_session_messages("s1")
        assert len(msgs) == 0
