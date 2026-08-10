from __future__ import annotations

import asyncio
from typing import Any

import pytest

from raven.channels.base import BaseChannel
from raven.core.db import Database
from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage, Message
from raven.core.plugin_loader import PluginLoader


class _BaseTestChannel(BaseChannel):
    channel_id = "base"

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def on_message(self, handler) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, session_id: str, message: Message) -> None: ...

    async def health_check(self) -> bool:
        return True


class SlowChannel(_BaseTestChannel):
    channel_id = "slow"

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.send_calls = 0

    async def send(self, session_id: str, message: Message) -> None:
        self.send_calls += 1
        await self.release.wait()


class EchoChannel(_BaseTestChannel):
    channel_id = "echo"

    def __init__(self) -> None:
        self.sent: list[Message] = []

    async def send(self, session_id: str, message: Message) -> None:
        self.sent.append(message)


class FailChannel(_BaseTestChannel):
    channel_id = "fail"

    def __init__(self) -> None:
        self.send_calls = 0

    async def send(self, session_id: str, message: Message) -> None:
        self.send_calls += 1
        raise ConnectionError("simulated network failure")


class FlakyChannel(_BaseTestChannel):
    channel_id = "flaky"

    def __init__(self, fail_until: int) -> None:
        self.fail_until = fail_until
        self.send_calls = 0
        self.sent: list[Message] = []

    async def send(self, session_id: str, message: Message) -> None:
        self.send_calls += 1
        if self.send_calls <= self.fail_until:
            raise ConnectionError("transient failure")
        self.sent.append(message)


@pytest.fixture
async def real_db(tmp_path) -> Any:
    db = Database(tmp_path / "test.db")
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
async def gateway(real_db, monkeypatch) -> Any:
    monkeypatch.setattr("raven.core.gateway.gateway.settings.dm_policy", "open")
    monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_allow_from", "")
    g = Gateway(db=real_db, plugin_loader=PluginLoader())
    g._running = True
    await g._outbox.start()
    yield g
    await g._outbox.stop()
    await g.stop()


@pytest.mark.asyncio
class TestChannelBulkhead:
    async def test_slow_channel_does_not_block_other_channels(self, gateway, monkeypatch) -> None:
        monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_send_timeout", 30.0)
        slow = SlowChannel()
        echo = EchoChannel()
        await gateway.register_channel(slow)
        await gateway.register_channel(echo)

        blocking = asyncio.create_task(gateway._send("slow", "s1", "blocking"))
        await asyncio.sleep(0.05)
        assert slow.send_calls == 1

        await gateway._send("echo", "s2", "fast")
        assert [m.content for m in echo.sent] == ["fast"]

        slow.release.set()
        await asyncio.wait_for(blocking, timeout=2.0)

    async def test_send_timeout_enqueues_to_outbox(self, gateway, monkeypatch) -> None:
        monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_send_timeout", 0.1)
        slow = SlowChannel()
        await gateway.register_channel(slow)

        await gateway._send("slow", "s1", "hello")
        assert slow.send_calls == 1
        assert await gateway._outbox.pending_count() == 1

    async def test_circuit_breaker_open_routes_to_outbox_without_send(self, gateway, monkeypatch) -> None:
        monkeypatch.setattr(
            "raven.core.gateway.gateway.settings.channel_send_failure_threshold", 3
        )
        fail = FailChannel()
        await gateway.register_channel(fail)

        for _ in range(3):
            await gateway._send("fail", "s1", "boom")
        assert fail.send_calls == 3

        cb = gateway._send_cbs["fail"]
        assert cb.is_open

        await gateway._send("fail", "s1", "after-open")
        assert fail.send_calls == 3, "circuit open must not attempt another send"
        assert await gateway._outbox.pending_count() == 4

    async def test_circuit_breaker_recovers_in_half_open(self, gateway, monkeypatch) -> None:
        monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_send_failure_threshold", 2)
        monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_send_recovery_timeout", 0.05)
        flaky = FlakyChannel(fail_until=2)
        await gateway.register_channel(flaky)

        await gateway._send("flaky", "s1", "one")
        await gateway._send("flaky", "s1", "two")
        assert gateway._send_cbs["flaky"].is_open

        await asyncio.sleep(0.1)
        await gateway._send("flaky", "s1", "three")
        assert flaky.send_calls == 3
        assert [m.content for m in flaky.sent] == ["three"]
        assert gateway._send_cbs["flaky"].state == "closed"

    async def test_dead_channel_cleans_up_bulkhead_state(self, gateway, monkeypatch) -> None:
        monkeypatch.setattr("raven.core.gateway.gateway.settings.channel_send_failure_threshold", 1)
        fail = FailChannel()
        await gateway.register_channel(fail)
        await gateway._send("fail", "s1", "boom")

        assert "fail" in gateway._send_semaphores
        assert "fail" in gateway._send_cbs
        await gateway._on_channel_dead("fail")
        assert "fail" not in gateway._send_semaphores
        assert "fail" not in gateway._send_cbs
