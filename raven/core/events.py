from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

Handler = Callable[..., Awaitable[None]]


class EventBus:
    """Simple pub/sub event bus for module communication."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event: str, handler: Handler) -> None:
        if handler not in self._subscribers[event]:
            self._subscribers[event].append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        handlers = self._subscribers.get(event)
        if handlers:
            with contextlib.suppress(ValueError):
                handlers.remove(handler)
            if not handlers:
                del self._subscribers[event]

    async def publish(self, event: str, **data: Any) -> None:
        handlers = list(self._subscribers.get(event, []))
        if not handlers:
            return
        results = await asyncio.gather(
            *[self._safe_dispatch(event, handler, data) for handler in handlers],
            return_exceptions=True,
        )
        for _, r in enumerate(results):
            if isinstance(r, BaseException):
                logger.error("[events] handler for '{}' raised: {}", event, r)

    async def _safe_dispatch(self, event: str, handler: Handler, data: dict[str, Any]) -> None:
        try:
            sig = inspect.signature(handler)
            kwargs = {k: v for k, v in data.items() if k in sig.parameters}
            await handler(**kwargs)
        except Exception:
            logger.opt(exception=True).error("[events] handler error for '{}'", event)

    def subscriber_count(self, event: str) -> int:
        return len(self._subscribers.get(event, []))

    @property
    def events(self) -> list[str]:
        return list(self._subscribers.keys())
