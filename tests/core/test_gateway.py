from __future__ import annotations

import re

import pytest

from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage
from tests.conftest import MockChannel


class TestGateway:
    async def test_gateway_init(self, gateway: Gateway):
        assert gateway.db is not None
        assert gateway.llm is not None
        assert gateway.plugin_loader is not None
        channels = await gateway.channels.list_ids()
        assert channels == ["mock"]

    async def test_register_channel(self, gateway: Gateway):
        channel = MockChannel()
        channel.channel_id = "test"
        await gateway.register_channel(channel)
        ch = await gateway.channels.get("test")
        assert ch is channel

    async def test_start_stop(self, gateway: Gateway):
        await gateway.start()
        assert gateway._running is True
        await gateway.stop()
        assert gateway._running is False

    async def test_handle_message_sends_response(self, gateway: Gateway):
        await gateway.start()
        event = IncomingMessage(channel="mock", user_id="u1", session_id="mock:u1", text="hello")
        await gateway.handle_message(event)
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        assert len(channel.sent_messages) > 0
        last = channel.sent_messages[-1]
        assert "Test response" in last.content
        await gateway.stop()

    async def test_closed_policy_blocks_user(self, gateway: Gateway, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "closed")
        await gateway.start()
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        event = IncomingMessage(channel="mock", user_id="blocked", session_id="mock:blocked", text="hello")
        await gateway.handle_message(event)
        assert len(channel.sent_messages) > 0
        last = channel.sent_messages[-1]
        assert "not authorized" in last.content.lower()
        await gateway.stop()

    async def test_pairing_records_the_request_and_keeps_the_code_off_the_channel(
        self, gateway: Gateway, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "pairing")
        await gateway.start()
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        event = IncomingMessage(channel="mock", user_id="new_user", session_id="mock:new_user", text="hello")
        await gateway.handle_message(event)
        assert len(channel.sent_messages) > 0
        reply = channel.sent_messages[-1].content.lower()
        assert "pairing code" not in reply
        assert "raven pairing approve" in reply
        row = await gateway.db.find_or_create_user("mock", "new_user")
        assert not row["is_allowed"]
        assert re.fullmatch(r"[A-Z0-9]{6}", str(row["pairing_code"])), "the operator needs a code to approve"
        await gateway.stop()

    async def test_pairing_does_not_admit_the_sender_who_repeats_the_code(
        self, gateway: Gateway, monkeypatch: pytest.MonkeyPatch
    ):
        """The welcome used to print the code and the same check accepted it back from the stranger who
        was sent it, so an unsolicited DM was a key: two messages, no operator, whole agent behind them."""
        monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "pairing")
        await gateway.start()
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        await gateway.handle_message(
            IncomingMessage(channel="mock", user_id="intruder", session_id="mock:intruder", text="hello")
        )
        code = str((await gateway.db.find_or_create_user("mock", "intruder"))["pairing_code"])
        await gateway.handle_message(
            IncomingMessage(channel="mock", user_id="intruder", session_id="mock:intruder", text=f"/pair {code}")
        )
        assert not (await gateway.db.find_or_create_user("mock", "intruder"))["is_allowed"]
        assert all("authorized" not in m.content.lower() for m in channel.sent_messages)
        await gateway.stop()

    async def test_pairing_code_survives_the_requests_that_follow_it(
        self, gateway: Gateway, monkeypatch: pytest.MonkeyPatch
    ):
        """One request, one code: re-prompting must not roll the credential the operator is reading."""
        monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "pairing")
        await gateway.start()
        await gateway.handle_message(
            IncomingMessage(channel="mock", user_id="noisy", session_id="mock:noisy", text="hello")
        )
        first = str((await gateway.db.find_or_create_user("mock", "noisy"))["pairing_code"])
        await gateway.handle_message(
            IncomingMessage(channel="mock", user_id="noisy", session_id="mock:noisy", text="hello again")
        )
        assert str((await gateway.db.find_or_create_user("mock", "noisy"))["pairing_code"]) == first
        await gateway.stop()

    async def test_double_start_raises(self, gateway: Gateway):
        await gateway.start()
        with pytest.raises(RuntimeError, match="already running"):
            await gateway.start()
        await gateway.stop()

    async def test_double_stop_does_not_raise(self, gateway: Gateway):
        await gateway.start()
        await gateway.stop()
        await gateway.stop()

    async def test_dropped_when_not_running(self, gateway: Gateway):
        channel = gateway.channels["mock"]
        assert isinstance(channel, MockChannel)
        event = IncomingMessage(channel="mock", user_id="u1", session_id="mock:u1", text="hello")
        await gateway.handle_message(event)
        assert len(channel.sent_messages) == 0

    async def test_gateway_init_has_service_layer(self, gateway: Gateway):
        assert gateway._extractor is not None
        assert gateway._chunker is not None
        assert gateway._persister is not None

    async def test_gateway_has_extractor(self, gateway: Gateway):
        assert gateway._extractor is not None
        assert gateway._chunker is not None
