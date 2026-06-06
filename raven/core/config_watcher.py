from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Callable

from loguru import logger


class ConfigWatcher:
    def __init__(self, env_path: str = ".env", check_interval: float = 5.0):
        self._env_path = Path(env_path)
        self._check_interval = check_interval
        self._last_mtime: float = 0.0
        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def on_change(self, fn: Callable[[], None]):
        self._listeners.append(fn)

    async def start(self):
        if self._env_path.exists():
            self._last_mtime = self._env_path.stat().st_mtime
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())

    async def _watch_loop(self):
        while self._running:
            await asyncio.sleep(self._check_interval)
            try:
                if self._env_path.exists():
                    mtime = self._env_path.stat().st_mtime
                    if mtime > self._last_mtime:
                        self._last_mtime = mtime
                        logger.info("[config] {} changed, reloading...", self._env_path.name)
                        self._reload_env()
                        for listener in self._listeners:
                            try:
                                listener()
                            except Exception as e:
                                logger.error("[config] listener error: {}", e)
            except Exception as e:
                logger.error("[config] watch error: {}", e)

    def _reload_env(self):
        if not self._env_path.exists():
            return
        with self._env_path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
