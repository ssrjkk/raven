from __future__ import annotations

import pytest

from raven.core.db import Database, DatabaseFactory
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
        assert "secrets" in tables

    async def test_conn_property_not_connected(self, tmp_path):
        d = Database(tmp_path / "nope.db")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = d.conn

    async def test_conn_property_connected(self, db):
        assert db.conn is not None

    async def test_disconnect(self, db):
        assert db._conn is not None
        await db.disconnect()
        assert db._conn is None

    async def test_disconnect_noop_when_closed(self):
        from pathlib import Path
        d = Database(Path("/tmp/nonexistent.db"))
        await d.disconnect()

    async def test_get_or_create_session(self, db):
        session = await db.get_or_create_session("s1", "telegram", "user1")
        assert session.id == "s1"
        assert session.channel == "telegram"

        session2 = await db.get_or_create_session("s1", "telegram", "user1")
        assert session2.id == "s1"

    async def test_get_or_create_session_custom_agent(self, db):
        session = await db.get_or_create_session("s2", "discord", "u2", agent_id="coder")
        assert session.agent_id == "coder"

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

    async def test_save_message_updates_session_updated_at(self, db):
        await db.get_or_create_session("s1", "telegram", "u1")
        before = (await db.get_or_create_session("s1", "telegram", "u1")).updated_at
        msg = Message(session_id="s1", channel="telegram", role="user", content="hi")
        await db.save_message(msg)
        after = (await db.get_or_create_session("s1", "telegram", "u1")).updated_at
        assert after >= before

    async def test_replace_session_messages(self, db):
        await db.get_or_create_session("s1", "telegram", "u1")
        msg = Message(session_id="s1", channel="telegram", role="user", content="old")
        await db.save_message(msg)
        assert len(await db.get_session_messages("s1")) == 1

        new_msgs = [
            {"role": "user", "content": "new1"},
            {"role": "assistant", "content": "new2"},
        ]
        await db.replace_session_messages("s1", new_msgs)
        msgs = await db.get_session_messages("s1")
        assert len(msgs) == 2
        contents = {m.content for m in msgs}
        assert "new1" in contents
        assert "new2" in contents

    async def test_replace_session_messages_empty(self, db):
        await db.get_or_create_session("s1", "telegram", "u1")
        await db.replace_session_messages("s1", [])
        assert len(await db.get_session_messages("s1")) == 0

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

    async def test_pending_pairing_users(self, db):
        u1 = await db.find_or_create_user("tg", "u1")
        u2 = await db.find_or_create_user("tg", "u2")
        await db.set_pairing_code(u1["id"], "code1")
        await db.set_pairing_code(u2["id"], "code2")
        pending = await db.get_pending_pairing_users()
        assert len(pending) == 2

    async def test_plugin_state(self, db):
        await db.save_plugin_state("memory", "key1", "value1")
        val = await db.get_plugin_state("memory", "key1")
        assert val == "value1"

        val2 = await db.get_plugin_state("memory", "nonexistent")
        assert val2 is None

    async def test_plugin_state_upsert(self, db):
        await db.save_plugin_state("p", "k", "v1")
        await db.save_plugin_state("p", "k", "v2")
        val = await db.get_plugin_state("p", "k")
        assert val == "v2"

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

    async def test_delete_session_cascades_messages(self, db):
        await db.get_or_create_session("s1", "tg", "u1")
        for i in range(3):
            await db.save_message(Message(session_id="s1", channel="tg", role="user", content=f"m{i}"))
        await db.delete_session("s1")
        async with db._conn.execute("SELECT * FROM messages WHERE session_id = 's1'") as c:
            rows = await c.fetchall()
        assert len(rows) == 0


class TestDatabaseMetrics:
    async def test_query_metrics_recorded(self, db):
        from raven.core.metrics import metrics

        metrics.clear()
        await db.get_or_create_session("m1", "telegram", "u1")
        await db.save_message(Message(session_id="m1", channel="telegram", role="user", content="hi"))
        await db.get_session_messages("m1")
        await db.find_or_create_user("telegram", "u1")
        snap = metrics.snapshot()
        counts = {k: v for k, v in snap.items() if k.startswith("raven_db_query") and k.endswith("_count")}
        assert sum(counts.values()) >= 4
        sums = {k: v for k, v in snap.items() if k.startswith("raven_db_query") and k.endswith("_sum")}
        assert len(sums) >= 4

    async def test_error_metric_on_failure(self, tmp_path):
        from raven.core.metrics import metrics

        d = Database(tmp_path / "test.db")
        await d.connect()
        metrics.clear()
        await d.disconnect()
        with pytest.raises(Exception):
            await d.get_session_messages("s1")
        snap = metrics.snapshot()
        errors = {k: v for k, v in snap.items() if k.startswith("raven_db_query") and k.endswith("_errors_total")}
        assert sum(errors.values()) == 1


class TestSecrets:
    async def test_save_and_get_secret(self, db):
        await db.save_secret("api_key", "encrypted_value")
        val = await db.get_secret("api_key")
        assert val == "encrypted_value"

    async def test_get_nonexistent_secret(self, db):
        val = await db.get_secret("nope")
        assert val is None

    async def test_upsert_secret(self, db):
        await db.save_secret("k", "v1")
        await db.save_secret("k", "v2")
        val = await db.get_secret("k")
        assert val == "v2"

    async def test_delete_secret(self, db):
        await db.save_secret("k", "v")
        await db.delete_secret("k")
        assert await db.get_secret("k") is None

    async def test_list_secrets(self, db):
        await db.save_secret("a", "1")
        await db.save_secret("c", "3")
        await db.save_secret("b", "2")
        keys = await db.list_secrets()
        assert keys == ["a", "b", "c"]

    async def test_list_secrets_empty(self, db):
        keys = await db.list_secrets()
        assert keys == []


class TestHealthCheck:
    async def test_healthy(self, db):
        assert await db.health_check() is True

    async def test_not_connected(self, tmp_path):
        d = Database(tmp_path / "nope.db")
        assert await d.health_check() is False


class TestDatabaseFactory:
    def test_factory_returns_database_for_sqlite(self):
        db = DatabaseFactory.create()
        assert isinstance(db, Database)


class TestIndexes:
    async def test_indexes_created(self, db):
        async with db._conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'") as c:
            names = {r[0] for r in await c.fetchall()}
        assert "idx_sessions_channel" in names
        assert "idx_messages_session_id" in names
        assert "idx_messages_created_at" in names
        assert "idx_users_channel" in names
        assert "idx_users_external_id" in names

    async def test_reconnect_idempotent(self, tmp_path):
        d = Database(tmp_path / "test.db")
        await d.connect()
        await d.connect()
        assert d._conn is not None
        async with d._conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as c:
            tables = {r[0] for r in await c.fetchall()}
        assert "sessions" in tables
        await d.disconnect()
