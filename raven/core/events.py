from __future__ import annotations

import asyncio
import contextlib
import inspect
import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

Handler = Callable[..., Awaitable[None]]

_DEFAULT_HISTORY_SIZE = 1000


class EventBus:
    """Simple pub/sub event bus for module communication."""

    def __init__(self, history_size: int = _DEFAULT_HISTORY_SIZE) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._lock = threading.Lock()

    def subscribe(self, event: str, handler: Handler) -> None:
        with self._lock:
            if handler not in self._subscribers[event]:
                self._subscribers[event].append(handler)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        with self._lock:
            handlers = self._subscribers.get(event)
            if handlers:
                with contextlib.suppress(ValueError):
                    handlers.remove(handler)
                if not handlers:
                    del self._subscribers[event]

    async def publish(self, event: str, **data: Any) -> None:
        with self._lock:
            self._history.append(
                {
                    "event": event,
                    "timestamp": time.time(),
                    "data": dict(data),
                }
            )
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
            params = sig.parameters
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
                kwargs = dict(data)
            else:
                kwargs = {k: v for k, v in data.items() if k in params}
            await handler(**kwargs)
        except Exception:
            logger.opt(exception=True).error("[events] handler error for '{}'", event)

    def subscriber_count(self, event: str) -> int:
        with self._lock:
            return len(self._subscribers.get(event, []))

    @property
    def events(self) -> list[str]:
        with self._lock:
            return list(self._subscribers.keys())

    def recent(self, event: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._history)
        if event is not None:
            items = [i for i in items if i["event"] == event]
        return items[-limit:]
