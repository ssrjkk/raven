from __future__ import annotations

import asyncio
import contextlib

import pytest

from raven.core.llm.queue import (
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    LLMQueueTimeoutError,
    PriorityAdmissionQueue,
)


class TestPriorityAdmissionQueue:
    async def test_acquire_immediate_under_concurrency(self):
        q = PriorityAdmissionQueue(2, queue_timeout=1.0)
        await q.acquire(PRIORITY_NORMAL)
        await q.acquire(PRIORITY_NORMAL)
        assert q.active == 2
        assert q.queued == 0
        await q.release()
        await q.release()
        assert q.active == 0

    async def test_release_wakes_waiter(self):
        q = PriorityAdmissionQueue(1, queue_timeout=5.0)
        await q.acquire(PRIORITY_NORMAL)
        result: list[str] = []

        async def waiter(name: str) -> None:
            await q.acquire(PRIORITY_NORMAL)
            result.append(name)
            await q.release()

        task = asyncio.create_task(waiter("w1"))
        await asyncio.sleep(0.01)
        assert q.queued == 1
        await q.release()
        await asyncio.wait_for(task, timeout=2.0)
        assert result == ["w1"]
        assert q.queued == 0

    async def test_priority_ordering(self):
        q = PriorityAdmissionQueue(1, queue_timeout=5.0)
        await q.acquire(PRIORITY_NORMAL)
        order: list[str] = []

        async def waiter(name: str, priority: float) -> None:
            await q.acquire(priority)
            order.append(name)
            await q.release()

        tasks = [
            asyncio.create_task(waiter("low", PRIORITY_LOW)),
            asyncio.create_task(waiter("normal", PRIORITY_NORMAL)),
            asyncio.create_task(waiter("high", PRIORITY_HIGH)),
        ]
        await asyncio.sleep(0.05)
        await q.release()
        await asyncio.sleep(0.05)
        await q.release()
        await asyncio.sleep(0.05)
        await q.release()
        for t in tasks:
            await asyncio.wait_for(t, timeout=2.0)
        assert order == ["high", "normal", "low"]

    async def test_fifo_within_same_priority(self):
        q = PriorityAdmissionQueue(1, queue_timeout=5.0)
        await q.acquire(PRIORITY_NORMAL)
        order: list[str] = []

        async def waiter(name: str) -> None:
            await q.acquire(PRIORITY_NORMAL)
            order.append(name)
            await q.release()

        tasks = [asyncio.create_task(waiter(f"w{i}")) for i in range(3)]
        await asyncio.sleep(0.02)
        for _ in range(3):
            await q.release()
            await asyncio.sleep(0.02)
        for t in tasks:
            await asyncio.wait_for(t, timeout=2.0)
        assert order == ["w0", "w1", "w2"]

    async def test_timeout_raises(self):
        q = PriorityAdmissionQueue(1, queue_timeout=0.05)
        await q.acquire(PRIORITY_NORMAL)
        with pytest.raises(LLMQueueTimeoutError):
            await q.acquire(PRIORITY_NORMAL)
        assert q.queued == 0
        await q.release()

    async def test_timeout_does_not_corrupt_queue(self):
        q = PriorityAdmissionQueue(1, queue_timeout=0.05)
        await q.acquire(PRIORITY_NORMAL)
        for _ in range(3):
            with pytest.raises(LLMQueueTimeoutError):
                await q.acquire(PRIORITY_NORMAL)
        assert q.queued == 0
        result: list[str] = []

        async def waiter() -> None:
            await q.acquire(PRIORITY_NORMAL)
            result.append("ok")
            await q.release()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        await q.release()
        await asyncio.wait_for(task, timeout=2.0)
        assert result == ["ok"]

    async def test_cancelled_waiter_skipped(self):
        q = PriorityAdmissionQueue(1, queue_timeout=5.0)
        await q.acquire(PRIORITY_NORMAL)
        result: list[str] = []

        async def waiter(name: str) -> None:
            await q.acquire(PRIORITY_NORMAL)
            result.append(name)
            await q.release()

        doomed = asyncio.create_task(waiter("doomed"))
        survivor = asyncio.create_task(waiter("survivor"))
        await asyncio.sleep(0.02)
        doomed.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await doomed
        await q.release()
        await asyncio.sleep(0.02)
        await q.release()
        await asyncio.wait_for(survivor, timeout=2.0)
        assert result == ["survivor"]

    async def test_set_concurrency(self):
        q = PriorityAdmissionQueue(1, queue_timeout=5.0)
        q.set_concurrency(3)
        for _ in range(3):
            await q.acquire(PRIORITY_NORMAL)
        assert q.active == 3


class TestPriorityConstants:
    def test_order(self):
        assert PRIORITY_HIGH < PRIORITY_NORMAL < PRIORITY_LOW
