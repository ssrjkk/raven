from __future__ import annotations

import json

import nats
from loguru import logger


class NATSClient:
    def __init__(self):
        self._nc = None
        self.connected = False

    async def connect(self, url: str = "nats://nats:4222"):
        try:
            self._nc = await nats.connect(url, name="agent-core")
            self.connected = True
            logger.info("Connected to NATS: {}", url)
        except Exception as e:
            logger.warning("NATS connection failed: {}", e)

    async def publish(self, subject: str, data: dict):
        if not self._nc:
            return
        try:
            await self._nc.publish(subject, json.dumps(data).encode())
        except Exception as e:
            logger.error("NATS publish failed: {}", e)

    async def close(self):
        if self._nc:
            await self._nc.close()
            self.connected = False
