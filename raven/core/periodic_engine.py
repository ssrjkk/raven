from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, TypeVar

from loguru import logger

ItemT = TypeVar("ItemT")
StatusT = TypeVar("StatusT")
StoreT = TypeVar("StoreT")


class PeriodicEngine(ABC, Generic[ItemT, StatusT, StoreT]):
    def __init__(
        self,
        store: StoreT,
        send_fn: Callable[[str, str], Any] | None = None,
    ):
        self._store = store
        self._send_fn = send_fn
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register_handler(self, key: str, handler: Callable[..., Any]):
        self._handlers[key] = handler

    async def start(self):
        self._running = True
        items = await self._list_active()
        for item in items:
            self._schedule_item(item)
        logger.info("{} started with {} items", type(self).__name__, len(items))

    async def stop(self):
        self._running = False
        for _id, task in list(self._tasks.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        logger.info("{} stopped", type(self).__name__)

    async def pause_item(self, item_id: str) -> bool:
        item = await self._load_item(item_id)
        if not item:
            return False
        await self._update_status(item_id, self._paused_status())
        task = self._tasks.pop(item_id, None)
        if task:
            task.cancel()
        return True

    async def resume_item(self, item_id: str) -> bool:
        item = await self._load_item(item_id)
        if not item:
            return False
        await self._update_status(item_id, self._active_status())
        if self._running:
            self._schedule_item(item)
        return True

    async def add_item(self, item: ItemT):
        await self._save_item(item)
        if self._is_active(item) and self._running:
            self._schedule_item(item)

    async def remove_item(self, item_id: str):
        task = self._tasks.pop(item_id, None)
        if task:
            task.cancel()
        await self._delete_item(item_id)

    def _schedule_item(self, item: ItemT):
        item_id = self._get_item_id(item)
        if item_id in self._tasks:
            self._tasks[item_id].cancel()
        self._tasks[item_id] = asyncio.create_task(self._run_loop(item))

    async def _run_loop(self, item: ItemT):
        while self._running:
            try:
                await self._run_item(item)
                await asyncio.sleep(self._get_interval(item))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("{} item {} loop error: {}", type(self).__name__, self._get_item_id(item), e)
                await asyncio.sleep(60)

    # --- abstract methods ---

    @abstractmethod
    async def _list_active(self) -> list[ItemT]: ...

    @abstractmethod
    async def _load_item(self, item_id: str) -> ItemT | None: ...

    @abstractmethod
    async def _save_item(self, item: ItemT): ...

    @abstractmethod
    async def _delete_item(self, item_id: str): ...

    @abstractmethod
    async def _update_status(self, item_id: str, status: StatusT): ...

    @abstractmethod
    def _get_item_id(self, item: ItemT) -> str: ...

    @abstractmethod
    def _is_active(self, item: ItemT) -> bool: ...

    @abstractmethod
    def _get_interval(self, item: ItemT) -> int | float: ...

    @abstractmethod
    async def _run_item(self, item: ItemT) -> Any: ...

    @abstractmethod
    def _paused_status(self) -> StatusT: ...

    @abstractmethod
    def _active_status(self) -> StatusT: ...
