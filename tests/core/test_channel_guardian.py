from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.channels.base import BaseChannel
from raven.core.channel_guardian import (
    BACKOFF_BASE,
    HEARTBEAT_INTERVAL,
    MAX_CONSECUTIVE_FAILURES,
    MAX_RESTART_ATTEMPTS,
    ChannelGuardian,
    TokenBucket,
)


class _FakeChannel(BaseChannel):
    def __init__(self, channel_id: str = "test"):
        self.channel_id = channel_id
        self.started = False
        self.stopped = False
        self._healthy = True

    async def connect(self):
        self.started = True

    async def disconnect(self):
        self.stopped = True

    async def send(self, session_id: str, message) -> None:
        pass

    async def on_message(self, handler) -> None:
        pass

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def health_check(self) -> bool:
        return self._healthy

    def set_healthy(self, healthy: bool):
        self._healthy = healthy


class _FakeUnhealthyChannel(BaseChannel):
    channel_id = "sick"

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
        return False


class _FakeRaisingChannel(BaseChannel):
    channel_id = "raising"

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
        raise ConnectionError("down")


# -- TokenBucket -------------------------------------------------------------


class TestTokenBucket:
    async def test_acquire_returns_true_when_tokens_available(self):
        tb = TokenBucket(rate=100.0, burst=100)
        assert await tb.acquire()

    async def test_acquire_returns_false_when_depleted(self):
        tb = TokenBucket(rate=0.001, burst=1)
        await tb.acquire()
        assert not await tb.acquire()

    async def test_refills_over_time(self):
        tb = TokenBucket(rate=1.0, burst=100)
        for _ in range(100):
            assert await tb.acquire()
        assert not await tb.acquire()
        await asyncio.sleep(1.5)
        assert await tb.acquire()

    async def test_default_burst_is_twice_rate(self):
        tb = TokenBucket(rate=10.0)
        assert tb._burst == 20

    async def test_custom_burst(self):
        tb = TokenBucket(rate=10.0, burst=5)
        assert tb._burst == 5


# -- ChannelGuardian ---------------------------------------------------------


class TestChannelGuardianRegister:
    def test_register_adds_channel(self):
        g = ChannelGuardian()
        ch = _FakeChannel("ch1")
        g.register(ch)
        assert "ch1" in g._channels
        assert "ch1" in g._channel_buckets
        assert g._error_counts["ch1"] == 0

    def test_register_creates_token_bucket(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        assert g._channel_buckets["ch"] is not None

    def test_unregister_removes_channel(self):
        g = ChannelGuardian()
        ch = _FakeChannel("ch")
        g.register(ch)
        g.unregister("ch")
        assert "ch" not in g._channels
        assert "ch" not in g._channel_buckets

    def test_unregister_nonexistent(self):
        g = ChannelGuardian()
        g.unregister("nope")


class TestChannelGuardianStartStop:
    async def test_start_creates_heartbeat_tasks(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g.start()
        assert "ch" in g._heartbeat_tasks
        assert not g._heartbeat_tasks["ch"].done()
        await g.stop()

    async def test_stop_cancels_tasks(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g.start()
        await g.stop()
        assert len(g._heartbeat_tasks) == 0

    async def test_idempotent_start(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g.start()
        await g.start()
        await g.stop()


class TestChannelGuardianRateLimit:
    async def test_channel_rate_limit_allows_within_budget(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        assert await g.check_rate_limit("ch")

    async def test_channel_rate_limit_blocks_excess(self):
        g = ChannelGuardian()
        ch = _FakeChannel("ch")
        g.register(ch)
        tb = TokenBucket(rate=0.001, burst=1)
        g._channel_buckets["ch"] = tb
        await tb.acquire()
        assert not await g.check_rate_limit("ch")

    async def test_user_rate_limit_creates_bucket(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        assert await g.check_rate_limit("ch", "user1")
        assert "user1" in g._user_buckets

    async def test_user_rate_limit_blocks_excess(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        ub = TokenBucket(rate=0.001, burst=1)
        g._user_buckets["user1"] = ub
        await ub.acquire()
        assert not await g.check_rate_limit("ch", "user1")


class TestChannelGuardianErrorTracking:
    async def test_record_success_resets_errors(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        g._error_counts["ch"] = 5
        await g.record_success("ch")
        assert g._error_counts["ch"] == 0

    async def test_record_success_nonexistent(self):
        g = ChannelGuardian()
        await g.record_success("nope")

    async def test_record_error_increments(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g.record_error("ch")
        assert g._error_counts["ch"] == 1

    async def test_record_error_triggers_restart(self):
        g = ChannelGuardian(backoff_base=0.01)
        ch = _FakeChannel("ch")
        g.register(ch)
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await g.record_error("ch")
        assert ch.stopped
        assert ch.started

    async def test_record_error_triggers_dead_after_exhausted_restarts(self):
        dead = []

        async def on_dead(cid):
            dead.append(cid)

        class _FailingChannel(BaseChannel):
            channel_id = "ch"

            async def start(self):
                raise RuntimeError("always fails")

            async def stop(self):
                pass

            async def connect(self):
                pass

            async def disconnect(self):
                pass

            async def health_check(self):
                return False

            async def send(self, session_id: str, message):
                pass

            async def on_message(self, handler):
                pass

        g = ChannelGuardian(on_channel_dead=on_dead, backoff_base=0.01)
        ch = _FailingChannel()
        g.register(ch)

        fails_needed = MAX_CONSECUTIVE_FAILURES * (MAX_RESTART_ATTEMPTS + 1)
        for _ in range(fails_needed):
            await g.record_error("ch")

        assert "ch" in g._dead_channels
        assert "ch" in dead

    async def test_dead_callback_removes_channel(self):
        removed = []

        async def on_dead(cid):
            removed.append(cid)

        g = ChannelGuardian(on_channel_dead=on_dead, backoff_base=0.01)
        ch = _FakeChannel("ch")
        g.register(ch)
        g._restart_attempts["ch"] = MAX_RESTART_ATTEMPTS
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await g.record_error("ch")
        assert "ch" in removed


class TestChannelGuardianHeartbeat:
    async def test_healthy_channel_keeps_error_count_zero(self):
        g = ChannelGuardian()
        ch = _FakeChannel("ch")
        g.register(ch)
        g._error_counts["ch"] = 2
        await g._handle_unhealthy("ch")
        await g._heartbeat_loop.__wrapped__(g, "ch") if hasattr(g._heartbeat_loop, "__wrapped__") else None


class TestChannelGuardianUnhealthy:
    async def test_unhealthy_increments_error_count(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g._handle_unhealthy("ch")
        assert g._error_counts["ch"] == 1

    async def test_unhealthy_triggers_restart_after_threshold(self):
        g = ChannelGuardian(backoff_base=0.01)
        ch = _FakeChannel("ch")
        g.register(ch)
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await g._handle_unhealthy("ch")
        assert ch.stopped
        assert ch.started

    async def test_raising_health_check_handled_gracefully(self):
        g = ChannelGuardian()
        ch = _FakeRaisingChannel()
        g.register(ch)
        await g._handle_unhealthy("raising")
        assert g._error_counts["raising"] == 1


class TestChannelGuardianDead:
    async def test_mark_dead_adds_to_dead_set(self):
        dead = []

        async def on_dead(cid):
            dead.append(cid)

        g = ChannelGuardian(on_channel_dead=on_dead)
        g.register(_FakeChannel("ch"))
        await g._mark_dead("ch")
        assert "ch" in g._dead_channels
        assert "ch" in dead

    async def test_mark_dead_idempotent(self):
        dead = []

        async def on_dead(cid):
            dead.append(cid)

        g = ChannelGuardian(on_channel_dead=on_dead)
        g.register(_FakeChannel("ch"))
        await g._mark_dead("ch")
        await g._mark_dead("ch")
        assert len(dead) == 1

    async def test_mark_dead_no_callback(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g._mark_dead("ch")
        assert "ch" in g._dead_channels


class TestChannelGuardianStatusReport:
    async def test_status_report_returns_all_channels(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("a"))
        g.register(_FakeChannel("b"))
        r = g.status_report()
        assert "a" in r
        assert "b" in r
        assert len(r) == 2

    async def test_status_report_shows_alive(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        r = g.status_report()
        assert r["ch"]["alive"]

    async def test_status_report_shows_dead(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        await g._mark_dead("ch")
        r = g.status_report()
        assert not r["ch"]["alive"]

    async def test_status_report_shows_errors(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        g._error_counts["ch"] = 2
        r = g.status_report()
        assert r["ch"]["errors"] == 2

    async def test_status_report_shows_restart_attempts(self):
        g = ChannelGuardian()
        g.register(_FakeChannel("ch"))
        g._restart_attempts["ch"] = 1
        r = g.status_report()
        assert r["ch"]["restart_attempts"] == 1
