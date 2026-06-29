from __future__ import annotations

import pytest


@pytest.mark.integration
class TestGatewayIntegration:
    async def test_db_connect(self, db) -> None:
        from raven.core.db import Database

        assert isinstance(db, Database)
        assert db._conn is not None

    async def test_user_crud(self, db) -> None:
        user = await db.find_or_create_user("test_channel", "test_user")
        assert user["id"] is not None
        assert user["channel"] == "test_channel"
        assert user["external_id"] == "test_user"

        same = await db.find_or_create_user("test_channel", "test_user")
        assert same["id"] == user["id"]

    async def test_session_crud(self, db) -> None:
        session = await db.get_or_create_session("session:1", "test_channel", "test_user")
        assert session.id is not None

        same = await db.get_or_create_session("session:1", "test_channel", "test_user")
        assert same.id == session.id

    async def test_message_save(self, db) -> None:
        from raven.core.models import Message

        session = await db.get_or_create_session("msg:session", "test_channel", "test_user")
        msg = Message(session_id=session.id, channel="test", role="user", content="hello")
        await db.save_message(msg)
        msgs = await db.get_session_messages(session.id)
        assert len(msgs) == 1
        assert msgs[0].content == "hello"

    async def test_health_metrics(self, db) -> None:
        from raven.core.health import health

        result = await health.check_all()
        assert isinstance(result, dict)
        assert "status" in result
