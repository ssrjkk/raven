from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from raven.channels.base import BaseChannel
from raven.core.db import Database
from raven.core.gateway.gateway import Gateway
from raven.core.metrics import metrics
from raven.core.models import IncomingMessage, Message
from raven.core.plugin_loader import PluginLoader
from tests.e2e.conftest import MockLLMProvider


class RealChannel(BaseChannel):
    channel_id = "real"

    def __init__(self) -> None:
        self.sent_messages: list[Message] = []
        self._handler: Any = None

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def send(self, session_id: str, message: Message) -> None:
        self.sent_messages.append(message)

    async def on_message(self, handler: Any) -> None:
        self._handler = handler

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True


@pytest.fixture
async def real_gateway(tmp_path: Path, monkeypatch) -> Any:
    monkeypatch.setattr("raven.core.gateway.gateway.settings.default_model", "mock-model")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.model_fast", "")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.model_balanced", "")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.model_quality", "")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "open")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.context_visibility", "public")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_allow_from", "")
    monkeypatch.setattr("raven.core.llm.router._HAS_TIER_CONFIG", None)

    db = Database(tmp_path / "full.db")
    await db.connect()

    g = Gateway(db=db, plugin_loader=PluginLoader(), redis_url=None)
    g.llm._providers["ollama"] = cast(Any, MockLLMProvider(["Full flow reply"]))
    channel = RealChannel()
    await g.register_channel(channel)
    channel._handler = g.handle_message
    g._running = True
    yield g
    await g.stop()
    await db.disconnect()


@pytest.mark.e2e
class TestFullFlowRealSqlite:
    async def test_user_created_in_db(self, real_gateway) -> None:
        event = IncomingMessage(
            channel="real",
            user_id="alice",
            session_id="real:alice:default",
            text="hello db",
        )
        await real_gateway.handle_message(event)
        user = await real_gateway.db.find_or_create_user("real", "alice")
        assert user is not None
        assert user["external_id"] == "alice"

    async def test_session_and_messages_persisted(self, real_gateway) -> None:
        event = IncomingMessage(
            channel="real",
            user_id="bob",
            session_id="real:bob:default",
            text="remember this",
        )
        await real_gateway.handle_message(event)
        session = await real_gateway.db.get_or_create_session("real:bob:default", "real", "bob")
        assert session.id == "real:bob:default"
        history = await real_gateway.db.get_session_messages("real:bob:default")
        texts = [m.content for m in history]
        assert any("remember this" in t for t in texts)

    async def test_stream_reply_delivered(self, real_gateway) -> None:
        event = IncomingMessage(
            channel="real",
            user_id="carol",
            session_id="real:carol:default",
            text="stream please",
        )
        await real_gateway.handle_message(event)
        channel = real_gateway.channels["real"]
        joined = " ".join(m.content for m in channel.sent_messages)
        assert "Full flow reply" in joined

    async def test_message_received_metric_counted(self, real_gateway) -> None:
        metrics.clear()
        event = IncomingMessage(
            channel="real",
            user_id="dave",
            session_id="real:dave:default",
            text="count me",
        )
        await real_gateway.handle_message(event)
        snap = metrics.snapshot()
        received = {
            k: v
            for k, v in snap.items()
            if k.startswith("raven_messages_received") and k.endswith("_total")
        }
        assert sum(received.values()) >= 1

    async def test_db_health_check_true(self, real_gateway) -> None:
        assert await real_gateway.db.health_check() is True
