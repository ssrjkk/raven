from __future__ import annotations

import json
import os
from typing import Any, Callable

from loguru import logger

try:
    from nats import connect as nats_connect
    from nats.aio.msg import Msg

    HAS_NATS = True
except ImportError:
    HAS_NATS = False


class NatsClient:
    def __init__(self, url: str | None = None):
        self._url = url or os.environ.get("NATS_URL", "nats://localhost:4222")
        self._conn = None
        self._subscriptions: list[Any] = []

    async def connect(self):
        if not HAS_NATS:
            logger.warning("NATS not available, running in standalone mode")
            return
        self._conn = await nats_connect(self._url)
        logger.info("Connected to NATS at {}", self._url)

    async def publish(self, subject: str, data: dict, headers: dict | None = None):
        if not self._conn:
            return
        await self._conn.publish(subject, json.dumps(data).encode(), headers=headers)

    async def subscribe(self, subject: str, callback: Callable[[dict], Any]):
        if not self._conn:
            return

        async def handler(msg: Msg):
            try:
                data = json.loads(msg.data.decode())
                await callback(data)
            except Exception as e:
                logger.error("NATS handler error: {}", e)

        sub = await self._conn.subscribe(subject, cb=handler)
        self._subscriptions.append(sub)

    async def close(self):
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        if self._conn:
            await self._conn.close()
