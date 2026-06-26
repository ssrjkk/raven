from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from loguru import logger

from .outbox import OutboxStore


class OutboxPoller:
    """Background poller that publishes outbox events to NATS.

    Runs in a service's lifespan: polls every 1s, publishes up to 50
    pending events per cycle, marks them published on success.
    Failed events are left for manual inspection.
    """

    def __init__(self, store: OutboxStore, nats_client: Any, poll_interval: float = 1.0):
        self._store = store
        self._nats = nats_client
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def poll_once(self):
        events = self._store.fetch_pending(batch_size=50)
        for event in events:
            try:
                headers_raw = json.loads(event["headers"])
                if self._nats:
                    await self._nats.publish(
                        event["subject"],
                        json.loads(event["payload"]),
                        headers=headers_raw,
                    )
                self._store.mark_published(event["id"])
            except Exception as e:
                self._store.mark_failed(event["id"], str(e))
                logger.error("Outbox publish failed for {}: {}", event["id"], e)

    def start(self):
        if self._task is None:
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
            logger.info("Outbox poller started (interval={}s)", self._poll_interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5.0)
            self._task = None

    async def _poll_loop(self):
        while self._running:
            try:
                events = self._store.fetch_pending(batch_size=50)
                for event in events:
                    try:
                        headers_raw = json.loads(event["headers"])
                        if self._nats:
                            await self._nats.publish(
                                event["subject"],
                                json.loads(event["payload"]),
                                headers=headers_raw,
                            )
                        self._store.mark_published(event["id"])
                    except Exception as e:
                        self._store.mark_failed(event["id"], str(e))
                        logger.error("Outbox publish failed for {}: {}", event["id"], e)
            except Exception as e:
                logger.error("Outbox poller error: {}", e)

            await asyncio.sleep(self._poll_interval)
