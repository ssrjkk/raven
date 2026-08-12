from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.circuit_breaker import CircuitBreakerOpenError
from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage
from tests.conftest import MockChannel


def _event(text: str, channel: str = "mock", user: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        user_id=user,
        session_id=f"{channel}:{user}:default",
        text=text,
        metadata={},
    )


class TestHandleMessageGuards:
    async def test_drops_when_not_running(self, gateway: Gateway):
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway.handle_message(_event("hello"))
        assert len(ch.sent_messages) == 0

    async def test_increments_metrics_on_receive(self, gateway: Gateway):
        await gateway.start()
        with patch("raven.core.gateway.gateway.metrics") as m:
            await gateway.handle_message(_event("hello"))
            m.inc.assert_any_call("messages_received", {"channel": "mock"})
        await gateway.stop()


class TestRateLimiting:
    async def test_rate_limiter_blocks(self, gateway: Gateway):
        await gateway.start()
        with patch.object(gateway._rate_limiter, "check_rate_limit", new_callable=AsyncMock, return_value=False):
            ch = gateway.channels["mock"]
            assert isinstance(ch, MockChannel)
            await gateway.handle_message(_event("hello"))
            assert len(ch.sent_messages) > 0
            assert "slow down" in ch.sent_messages[-1].content.lower()
        await gateway.stop()

    async def test_guardian_rate_limiter_blocks(self, gateway: Gateway):
        await gateway.start()
        with patch.object(gateway._guardian, "check_rate_limit", new_callable=AsyncMock, return_value=False):
            ch = gateway.channels["mock"]
            assert isinstance(ch, MockChannel)
            await gateway.handle_message(_event("hello"))
            assert len(ch.sent_messages) > 0
            assert "slow down" in ch.sent_messages[-1].content.lower()
        await gateway.stop()

    async def test_redis_rate_limiter_blocks_when_present(self, gateway: Gateway):
        await gateway.start()
        mock_redis = AsyncMock()
        mock_redis.is_allowed = AsyncMock(return_value=False)
        gateway._redis_rate_limiter = mock_redis
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway.handle_message(_event("hello"))
        assert len(ch.sent_messages) > 0
        assert "slow down" in ch.sent_messages[-1].content.lower()
        gateway._redis_rate_limiter = None
        await gateway.stop()

    async def test_all_rate_limiters_pass(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway.handle_message(_event("hello"))
        assert len(ch.sent_messages) > 0
        assert "test response" in ch.sent_messages[-1].content.lower()
        await gateway.stop()


class TestCircuitBreaker:
    async def test_circuit_breaker_open_sends_error(self, gateway: Gateway):
        await gateway.start()
        with patch.object(
            gateway._message_cb, "call", new_callable=AsyncMock, side_effect=CircuitBreakerOpenError("test")
        ):
            ch = gateway.channels["mock"]
            assert isinstance(ch, MockChannel)
            await gateway.handle_message(_event("hello"))
            assert len(ch.sent_messages) > 0
            assert "unavailable" in ch.sent_messages[-1].content.lower()
        await gateway.stop()

    async def test_generic_exception_sends_error(self, gateway: Gateway):
        await gateway.start()
        with patch.object(
            gateway._message_cb, "call", new_callable=AsyncMock, side_effect=RuntimeError("boom")
        ), patch("raven.core.gateway.gateway.metrics") as m:
            ch = gateway.channels["mock"]
            assert isinstance(ch, MockChannel)
            await gateway.handle_message(_event("hello"))
            assert len(ch.sent_messages) > 0
            assert "error occurred" in ch.sent_messages[-1].content.lower()
            m.inc.assert_any_call("message_errors", {"channel": "mock", "reason": "handler"})
        await gateway.stop()


class TestSendMethod:
    async def test_send_records_success(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway._send("mock", "mock:u1:test", "hello world")
        assert len(ch.sent_messages) > 0
        assert ch.sent_messages[-1].content == "hello world"
        assert gateway._guardian._error_counts.get("mock", 0) == 0
        await gateway.stop()

    async def test_send_records_error_on_failure(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        with patch.object(ch, "send", new_callable=AsyncMock, side_effect=Exception("send failed")):
            await gateway._send("mock", "mock:u1:test", "hello")
        assert gateway._guardian._error_counts.get("mock", 0) > 0
        await gateway.stop()

    async def test_send_nonexistent_channel(self, gateway: Gateway):
        await gateway.start()
        await gateway._send("nonexistent", "session", "hello")
        await gateway.stop()

    async def test_send_streaming_records_success(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        mock_stream = AsyncMock()
        setattr(ch, "send_stream", mock_stream)  # noqa: B010
        await gateway._send("mock", "mock:u1:test", "streaming text", streaming=True)
        mock_stream.assert_awaited_once()
        await gateway.stop()

    async def test_send_streaming_fallback_to_regular(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        assert not hasattr(ch, "send_stream") or ch.send_stream is None
        await gateway._send("mock", "mock:u1:test", "text", streaming=True)
        assert len(ch.sent_messages) > 0
        await gateway.stop()

    async def test_send_streaming_error_records_failure(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        setattr(ch, "send_stream", AsyncMock(side_effect=Exception("stream failed")))  # noqa: B010
        await gateway._send("mock", "mock:u1:test", "text", streaming=True)
        assert gateway._guardian._error_counts.get("mock", 0) > 0
        await gateway.stop()


class TestOnChannelDead:
    async def test_removes_channel_and_sends_alert(self, gateway: Gateway):
        await gateway.start()
        ch2 = MockChannel()
        ch2.channel_id = "second"
        await gateway.register_channel(ch2)
        await gateway._on_channel_dead("mock")
        remaining = await gateway.channels.list_ids()
        assert "mock" not in remaining
        assert "second" in remaining
        assert len(ch2.sent_messages) > 0
        assert "dead" in ch2.sent_messages[-1].content.lower()
        await gateway.stop()

    async def test_no_alert_when_no_remaining(self, gateway: Gateway):
        await gateway.start()
        await gateway._on_channel_dead("mock")
        remaining = await gateway.channels.list_ids()
        assert "mock" not in remaining
        assert len(remaining) == 0
        await gateway.stop()


class TestHandleMessageInnerRouting:
    async def test_command_message_handled(self, gateway: Gateway):
        await gateway.start()
        await gateway._handle_command(_event("/help"), {"id": "u1", "role": "user"})
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        assert len(ch.sent_messages) > 0
        await gateway.stop()

    async def test_non_command_message_reaches_processor(self, gateway: Gateway):
        await gateway.start()
        with patch.object(gateway._message_processor, "process", new_callable=AsyncMock) as mock_proc:
            await gateway._handle_message_inner(_event("hello there"), "cid1")
            mock_proc.assert_awaited_once()
        await gateway.stop()

    async def test_orchestrator_routing_for_agent_profile(self, gateway: Gateway):
        await gateway.start()
        with patch.object(gateway, "_handle_with_orchestrator", new_callable=AsyncMock) as mock_h:
            user = {"id": "u_arch", "name": "Arch", "role": "user", "agent_profile": "coder"}
            with patch.object(gateway.db, "find_or_create_user", new_callable=AsyncMock, return_value=user):
                await gateway._handle_message_inner(
                    IncomingMessage(channel="mock", user_id="u_arch", session_id="mock:u_arch:default", text="code this"),
                    "cid2",
                )
                mock_h.assert_awaited_once()
        await gateway.stop()

    async def test_full_handle_message_end_to_end(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway.handle_message(_event("hello"))
        assert len(ch.sent_messages) > 0
        last = ch.sent_messages[-1]
        assert "test response" in last.content.lower()
        await gateway.stop()
