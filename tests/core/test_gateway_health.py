from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.channels.base import BaseChannel
from raven.core.gateway.gateway import Gateway
from tests.conftest import MockChannel


class _SlowStartChannel(BaseChannel):
    channel_id = "slow_start"

    def __init__(self):
        self.started = False
        self.stopped = False
        self._ready = False

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send(self, session_id: str, message) -> None:
        pass

    async def on_message(self, handler) -> None:
        pass

    async def start(self):
        self.started = True
        self._ready = True

    async def stop(self):
        self.stopped = True
        self._ready = False

    async def health_check(self) -> bool:
        return self._ready


class _FailingHealthChannel(BaseChannel):
    channel_id = "failing_health"

    def __init__(self):
        self._healthy = True

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send(self, session_id: str, message) -> None:
        pass

    async def on_message(self, handler) -> None:
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    async def health_check(self) -> bool:
        return self._healthy


class TestLlmHealthCheck:
    async def test_llm_health_check_success(self, gateway: Gateway):
        result = await gateway._llm_health_check()
        assert isinstance(result, bool)

    async def test_llm_health_check_failure(self, gateway: Gateway):
        with patch.object(gateway.llm, "complete", new_callable=AsyncMock, side_effect=Exception("LLM down")):
            result = await gateway._llm_health_check()
            assert result is False

    async def test_llm_health_check_cached_within_ttl(self, gateway: Gateway):
        with patch.object(
            gateway.llm, "complete", new_callable=AsyncMock, return_value=MagicMock(content="ok")
        ) as mock_complete:
            first = await gateway._llm_health_check()
            second = await gateway._llm_health_check()
            assert first is True
            assert second is True
            mock_complete.assert_awaited_once()

    async def test_llm_health_check_failure_cached(self, gateway: Gateway):
        with patch.object(
            gateway.llm, "complete", new_callable=AsyncMock, side_effect=Exception("LLM down")
        ) as mock_complete:
            assert await gateway._llm_health_check() is False
            assert await gateway._llm_health_check() is False
            mock_complete.assert_awaited_once()

    async def test_llm_restart_resets_health_cache(self, gateway: Gateway):
        with patch.object(gateway.llm, "complete", new_callable=AsyncMock, side_effect=Exception("LLM down")):
            assert await gateway._llm_health_check() is False
        await gateway._llm_restart()
        with patch.object(
            gateway.llm, "complete", new_callable=AsyncMock, return_value=MagicMock(content="ok")
        ) as mock_complete:
            assert await gateway._llm_health_check() is True
            mock_complete.assert_awaited_once()


class TestDbRestart:
    async def test_db_restart(self, gateway: Gateway):
        with patch.object(gateway.db, "disconnect", new_callable=AsyncMock) as mock_disc, patch.object(
            gateway.db, "connect", new_callable=AsyncMock
        ) as mock_conn:
            await gateway._db_restart()
            mock_disc.assert_awaited_once()
            mock_conn.assert_awaited_once()


class TestLlmRestart:
    async def test_llm_restart_creates_new_router(self, gateway: Gateway):
        old_llm = gateway.llm
        await gateway._llm_restart()
        assert gateway.llm is not old_llm
        assert gateway.failover is not None


class TestChannelDeadIntegration:
    async def test_on_channel_dead_removes_from_channel_manager(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway._on_channel_dead("mock")
        remaining = await gateway.channels.list_ids()
        assert "mock" not in remaining
        await gateway.stop()

    async def test_on_channel_dead_stops_channel(self, gateway: Gateway):
        await gateway.start()
        ch = MockChannel()
        ch.channel_id = "to_die"
        await gateway.register_channel(ch)
        await gateway._on_channel_dead("to_die")
        assert "to_die" not in await gateway.channels.list_ids()
        await gateway.stop()

    async def test_on_channel_dead_logs_and_sends_alerts(self, gateway: Gateway):
        await gateway.start()
        ch2 = MockChannel()
        ch2.channel_id = "survivor"
        await gateway.register_channel(ch2)
        await gateway._on_channel_dead("mock")
        assert len(ch2.sent_messages) > 0
        assert "dead" in ch2.sent_messages[-1].content.lower()
        await gateway.stop()


class TestGuardianIntegration:
    async def test_guardian_created_in_gateway(self, gateway: Gateway):
        from raven.core.channel_guardian import ChannelGuardian

        assert isinstance(gateway._guardian, ChannelGuardian)

    async def test_guardian_has_channels_after_start(self, gateway: Gateway):
        await gateway.start()
        report = gateway._guardian.status_report()
        assert "mock" in report
        assert report["mock"]["alive"]
        await gateway.stop()

    async def test_send_records_guardian_success(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        await gateway._send("mock", "s1", "hello")
        assert gateway._guardian._error_counts.get("mock", 0) == 0
        await gateway.stop()

    async def test_send_records_guardian_error(self, gateway: Gateway):
        await gateway.start()
        ch = gateway.channels["mock"]
        assert isinstance(ch, MockChannel)
        with patch.object(ch, "send", new_callable=AsyncMock, side_effect=Exception("fail")):
            await gateway._send("mock", "s1", "hello")
        assert gateway._guardian._error_counts.get("mock", 0) > 0
        await gateway.stop()
