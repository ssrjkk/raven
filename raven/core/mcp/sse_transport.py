from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger


class SSETransport:
    def __init__(self, ping_timeout: float = 30.0) -> None:
        self._subscribers: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._running = False
        self._ping_timeout = ping_timeout

    async def start(self) -> None:
        self._running = True
        logger.debug("[sse] transport started")

    async def stop(self) -> None:
        self._running = False
        for q in self._subscribers.values():
            await q.put({"event": "close", "data": ""})
        self._subscribers.clear()
        logger.debug("[sse] transport stopped")

    def subscribe(self, client_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[client_id] = q
        return q

    def unsubscribe(self, client_id: str) -> None:
        self._subscribers.pop(client_id, None)

    async def send(self, event: str, data: Any) -> None:
        payload = {"event": event, "data": data if isinstance(data, str) else json.dumps(data, default=str)}
        dead: list[str] = []
        for cid, q in self._subscribers.items():
            try:
                await asyncio.wait_for(q.put(payload), timeout=1.0)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self._subscribers.pop(cid, None)
            logger.debug("[sse] dropped slow subscriber {}", cid)

    async def stream(self, client_id: str) -> AsyncIterator[str]:
        q = self._subscribers.get(client_id)
        if q is None:
            return
        while self._running:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=self._ping_timeout)
            except TimeoutError:
                yield "event: ping\ndata: \n\n"
                continue
            if msg.get("event") == "close":
                break
            yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"

    async def broadcast(self, event: str, data: Any) -> None:
        await self.send(event, data)
