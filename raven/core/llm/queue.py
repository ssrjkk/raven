from __future__ import annotations

import asyncio
import heapq

from loguru import logger

PRIORITY_HIGH = -1.0
PRIORITY_NORMAL = 0.0
PRIORITY_LOW = 1.0

_BACKPRESSURE_THRESHOLD = 50


class LLMQueueTimeoutError(RuntimeError):
    """Raised when a request waits too long in the LLM admission queue."""


class PriorityAdmissionQueue:
    """Admission control for LLM calls with priority ordering and bounded wait.

    Requests are admitted while fewer than ``concurrency`` are in flight.
    When capacity is exhausted, waiting requests are ordered by priority
    (lower numeric value runs first; equal priorities are FIFO). A request
    that waits longer than ``queue_timeout`` seconds raises
    :class:`LLMQueueTimeoutError` so callers can degrade gracefully instead
    of piling up unbounded backpressure.
    """

    def __init__(self, concurrency: int, queue_timeout: float = 5.0) -> None:
        self._concurrency = max(1, concurrency)
        self._queue_timeout = queue_timeout
        self._active = 0
        self._cond = asyncio.Condition()
        self._heap: list[tuple[float, int, asyncio.Future[None]]] = []
        self._seq = 0
        self._enqueued = 0

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def active(self) -> int:
        return self._active

    @property
    def queued(self) -> int:
        return len(self._heap)

    def set_concurrency(self, concurrency: int) -> None:
        self._concurrency = max(1, concurrency)

    async def acquire(self, priority: float = PRIORITY_NORMAL) -> None:
        fut: asyncio.Future[None] | None = None
        async with self._cond:
            if self._active < self._concurrency and not self._heap:
                self._active += 1
                return
            self._seq += 1
            self._enqueued += 1
            fut = asyncio.get_running_loop().create_future()
            heapq.heappush(self._heap, (priority, self._seq, fut))
            queued = len(self._heap)
            if queued >= _BACKPRESSURE_THRESHOLD and queued % _BACKPRESSURE_THRESHOLD == 0:
                logger.warning(
                    "LLM backpressure: {} requests queued, concurrency limit {}", queued, self._concurrency
                )
        assert fut is not None
        try:
            await asyncio.wait_for(fut, timeout=self._queue_timeout)
        except TimeoutError:
            async with self._cond:
                if fut.done() and not fut.cancelled():
                    return
                for i, item in enumerate(self._heap):
                    if item[2] is fut:
                        del self._heap[i]
                        heapq.heapify(self._heap)
                        break
            raise LLMQueueTimeoutError(
                f"LLM admission queue timed out after {self._queue_timeout}s "
                f"(concurrency={self._concurrency}, queued={len(self._heap)})"
            ) from None

    async def release(self) -> None:
        async with self._cond:
            self._active -= 1
            while self._heap:
                _, _, fut = heapq.heappop(self._heap)
                if fut.cancelled():
                    continue
                self._active += 1
                fut.set_result(None)
                return
