from __future__ import annotations

import asyncio
import time

import pytest

from raven.core.models import IncomingMessage
from tests.e2e.conftest import MockChannel


@pytest.mark.e2e
@pytest.mark.load
class TestStress:
    async def test_concurrent_messages(self, gateway):
        channel = gateway.channels["mock"]
        count = 50

        async def send_message(i: int) -> float:
            t0 = time.monotonic()
            event = IncomingMessage(
                channel="mock",
                user_id=f"user{i % 10}",
                session_id=f"mock:user{i}:default",
                text=f"stress test message {i}",
            )
            await gateway.handle_message(event)
            return time.monotonic() - t0

        tasks = [send_message(i) for i in range(count)]
        latencies = await asyncio.gather(*tasks)

        assert len(channel.sent_messages) >= count
        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        print(f"\nStress test: {count} messages, avg={avg_latency:.3f}s, max={max_latency:.3f}s")
        assert max_latency < 30.0, f"Max latency {max_latency:.3f}s exceeds 30s threshold"

    async def test_burst_rate_limiting(self, gateway):
        channel = gateway.channels["mock"]
        count = 20

        async def fire(i: int) -> float:
            t0 = time.monotonic()
            event = IncomingMessage(
                channel="mock",
                user_id="burst_user",
                session_id="mock:burst_user:default",
                text=f"burst {i}",
            )
            await gateway.handle_message(event)
            return time.monotonic() - t0

        tasks = [fire(i) for i in range(count)]
        await asyncio.gather(*tasks)

        rate_limited = sum(1 for e in channel.sent_messages if "slow down" in e.content.lower())
        print(f"\nBurst test: {count} messages, {rate_limited} rate-limited responses")
        assert rate_limited < count, "All messages were rate-limited"
