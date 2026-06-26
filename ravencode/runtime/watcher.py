from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from loguru import logger


class FileWatcher:
    def __init__(self, paths: list[str], interval: float = 1.0) -> None:
        self._paths = [Path(p).expanduser().resolve() for p in paths]
        self._interval = interval
        self._snapshots: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._on_change: Callable[[str], Awaitable[None]] | None = None

    def on_change(self, handler: Callable[[str], Awaitable[None]]) -> None:
        self._on_change = handler

    async def start(self) -> None:
        self._running = True
        self._take_snapshot()
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def _take_snapshot(self) -> None:
        for p in self._paths:
            if p.is_file():
                self._snapshots[str(p)] = p.stat().st_mtime

    async def _poll(self) -> None:
        while self._running:
            await asyncio.sleep(self._interval)
            for p in self._paths:
                if not p.is_file():
                    continue
                key = str(p)
                mtime = p.stat().st_mtime
                prev = self._snapshots.get(key)
                if prev is not None and mtime != prev:
                    self._snapshots[key] = mtime
                    logger.info("File changed: {}", key)
                    if self._on_change:
                        try:
                            await self._on_change(key)
                        except Exception as exc:
                            logger.error("Change handler failed: {}", exc)
                elif prev is None:
                    self._snapshots[key] = mtime


_watcher: FileWatcher | None = None


def get_watcher(paths: list[str] | None = None) -> FileWatcher:
    global _watcher
    if _watcher is None:
        _watcher = FileWatcher(paths or ["."])
    return _watcher


async def watch_files(paths: list[str]) -> str:
    watcher = get_watcher(paths)
    await watcher.start()
    return f"[ok] watching {len(paths)} file(s)"
