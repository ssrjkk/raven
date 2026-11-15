from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from pathlib import Path

from loguru import logger


class ConfigWatcher:
    def __init__(self, env_path: str | None = None, check_interval: float = 5.0):
        if env_path is None:
            from raven.core.config import effective_env_file

            env_path = str(effective_env_file())
        self._env_path = Path(env_path)
        self._check_interval = check_interval
        self._last_mtime: float = 0.0
        self._listeners: list[Callable[[], object]] = []
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def env_path(self) -> Path:
        """The one file being watched — a switch written anywhere else is not picked up."""
        return self._env_path

    def add_listener(self, callback: Callable[[], object]) -> None:
        """Register a callable run after every reload.

        Pushing values into ``os.environ`` is not enough: ``Settings`` read the environment once at
        import, so the listeners are what make a written value change the behaviour of a running gateway.
        """
        self._listeners.append(callback)

    def _get_mtime(self) -> float:
        return self._env_path.stat().st_mtime

    async def start(self):
        if await asyncio.to_thread(self._env_path.exists):
            mtime = await asyncio.to_thread(self._get_mtime)
            self._last_mtime = mtime
        self._running = True
        self._task = asyncio.create_task(self._watch_loop())

    async def _watch_loop(self):
        while self._running:
            await asyncio.sleep(self._check_interval)
            try:
                if await asyncio.to_thread(self._env_path.exists):
                    mtime = await asyncio.to_thread(self._get_mtime)
                    if mtime > self._last_mtime:
                        self._last_mtime = mtime
                        logger.info("[config] {} changed, reloading...", self._env_path.name)
                        await asyncio.to_thread(self._reload_env)
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
        from raven.core.config import parse_env_file

        os.environ.update(parse_env_file(self._env_path))

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
