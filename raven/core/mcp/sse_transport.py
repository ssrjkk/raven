from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

# One client that stops reading must not become an unbounded buffer, and it must not be able to hold
# the publisher either. A queue that cannot fill makes the drop path below unreachable: measured with
# `SSETransport().subscribe("c").maxsize`, the old queue reported 0 (unbounded), so `send()` never saw
# a full queue and a wedged browser tab kept every event it would never read.
_DEFAULT_MAX_PENDING = 256


class SSETransport:
    def __init__(self, ping_timeout: float = 30.0, max_pending: int = _DEFAULT_MAX_PENDING) -> None:
        self._subscribers: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._running = True
        self._ping_timeout = ping_timeout
        self._max_pending = max_pending

    async def start(self) -> None:
        self._running = True
        logger.debug("[sse] transport started")

    async def stop(self) -> None:
        self._running = False
        for client_id in list(self._subscribers):
            self.unsubscribe(client_id)
        logger.debug("[sse] transport stopped")

    def subscribe(self, client_id: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_pending)
        self._subscribers[client_id] = q
        return q

    def unsubscribe(self, client_id: str) -> None:
        q = self._subscribers.pop(client_id, None)
        if q is not None:
            # Wake a read already parked on this queue. Without it the loop learns the client left only
            # when the ping timer fires, so a disconnected browser holds a task and a buffer for
            # `ping_timeout` seconds — 30 by default, on every reload of the page.
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait({"event": "close", "data": ""})

    async def send(self, event: str, data: Any) -> None:
        if not self._running:
            return
        payload = {"event": event, "data": data if isinstance(data, str) else json.dumps(data, default=str)}
        for cid in list(self._subscribers):
            q = self._subscribers[cid]
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                self._subscribers.pop(cid, None)
                logger.warning("[sse] dropped {} after {} undelivered events", cid, self._max_pending)

    async def stream(self, client_id: str) -> AsyncIterator[str]:
        while self._running:
            # Resolved per iteration: `unsubscribe()` is the other way a stream can be orphaned, and a
            # queue captured on entry would keep a client that already left on the ping timer forever.
            q = self._subscribers.get(client_id)
            if q is None:
                return
            try:
                msg = await asyncio.wait_for(q.get(), timeout=self._ping_timeout)
            except TimeoutError:
                yield "event: ping\ndata: \n\n"
                continue
            if msg.get("event") == "close":
                return
            yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"

    async def broadcast(self, event: str, data: Any) -> None:
        await self.send(event, data)


_transport = SSETransport()


def shared_transport() -> SSETransport:
    """The one registry the publisher and the readers share.

    A module-level instance per transport file was the reason the stream was silent: `tools/call`
    answers from `server.py` and `/mcp/events` reads from `http_transport.py`, and two instances make
    those two halves invisible to each other.
    """
    return _transport


async def publish_tool_event(name: str, status: str) -> None:
    """Tell `/mcp/events` that a tool ran: the name and the verdict, nothing else.

    Arguments and results stay out — they carry file contents and shell command lines, and the stream
    fans one payload out to every subscriber, so a second observer would read the first one's work.
    """
    await shared_transport().send("tool_call", {"tool": name, "status": status})
