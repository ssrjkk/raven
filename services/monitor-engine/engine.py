from __future__ import annotations

import asyncio

from loguru import logger


class MonitorEngine:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Monitor engine started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def _loop(self):
        while self._running:
            await asyncio.sleep(30)
