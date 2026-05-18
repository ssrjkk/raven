from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger


class Backpressure(str, Enum):
    DROP = "drop"
    BLOCK = "block"
    THROTTLE = "throttle"


@dataclass
class SessionInfo:
    created_at: float = 0.0
    last_get: float = 0.0
    event_count: int = 0
    last_event_id: str = ""


_EVENT_ID_COUNTER: int = 0


def _next_event_id() -> str:
    global _EVENT_ID_COUNTER
    _EVENT_ID_COUNTER += 1
    return f"evt-{int(time.time() * 1000)}-{_EVENT_ID_COUNTER}"


class SSEEvent:
    def __init__(self, event: str, data: Any, retry: int | None = None, event_id: str | None = None):
        self.event = event
        self.data = data
        self.retry = retry
        self.id = event_id or _next_event_id()

    def serialize(self) -> str:
        lines: list[str] = []
        if self.retry is not None:
            lines.append(f"retry: {self.retry}")
        lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event}")
        payload = json.dumps(self.data, default=str)
        for line in payload.splitlines():
            lines.append(f"data: {line}")
        lines.append("")
        lines.append("")
        return "\n".join(lines)


class SSEStream:
    def __init__(self, max_queue: int = 512, backpressure: Backpressure = Backpressure.DROP):
        self._max_queue = max_queue
        self._backpressure = backpressure
        self._queues: dict[str, asyncio.Queue] = {}
        self._sessions: dict[str, SessionInfo] = {}
        self._cleanup_interval = 60.0
        self._task: asyncio.Task | None = None
        self._total_pushed = 0
        self._total_dropped = 0

    @property
    def active_sessions(self) -> int:
        return len(self._queues)

    @property
    def total_pushed(self) -> int:
        return self._total_pushed

    @property
    def total_dropped(self) -> int:
        return self._total_dropped

    def subscribe(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue(maxsize=self._max_queue)
            self._sessions[session_id] = SessionInfo(created_at=time.time(), last_get=time.time())
        return self._queues[session_id]

    def unsubscribe(self, session_id: str):
        self._queues.pop(session_id, None)
        self._sessions.pop(session_id, None)

    def _track_get(self, session_id: str):
        info = self._sessions.get(session_id)
        if info:
            info.last_get = time.time()
            info.event_count += 1

    def _track_event_id(self, session_id: str, event_id: str):
        info = self._sessions.get(session_id)
        if info:
            info.last_event_id = event_id

    def get_session_info(self, session_id: str) -> SessionInfo | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> dict[str, dict]:
        now = time.time()
        return {
            sid: {
                "created_at": info.created_at,
                "age_seconds": round(now - info.created_at, 1),
                "idle_seconds": round(now - info.last_get, 1),
                "events": info.event_count,
                "last_event_id": info.last_event_id,
                "queue_size": self._queues[sid].qsize() if sid in self._queues else 0,
            }
            for sid, info in self._sessions.items()
        }

    async def push(self, event: str, data: Any, session_id: str | None = None):
        payload = SSEEvent(event, data)

        if session_id:
            q = self._queues.get(session_id)
            if q is None:
                return
            await self._push_to_queue(q, payload, session_id)
        else:
            for sid, q in list(self._queues.items()):
                await self._push_to_queue(q, payload, sid)

    async def broadcast(self, event: str, data: Any):
        await self.push(event, data)

    async def _push_to_queue(self, q: asyncio.Queue, payload: SSEEvent, session_id: str):
        if self._backpressure == Backpressure.DROP:
            try:
                await asyncio.wait_for(q.put(payload), timeout=0.1)
                self._total_pushed += 1
                self._track_event_id(session_id, payload.id)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                self._total_dropped += 1
                logger.warning("SSE queue full for session {}, dropping event {}", session_id, payload.event)
        elif self._backpressure == Backpressure.BLOCK:
            try:
                await q.put(payload)
                self._total_pushed += 1
                self._track_event_id(session_id, payload.id)
            except asyncio.QueueFull:
                self._total_dropped += 1
                logger.warning("SSE queue full for session {}, blocking dropped {}", session_id, payload.event)
        elif self._backpressure == Backpressure.THROTTLE:
            if q.qsize() >= self._max_queue:
                try:
                    q.get_nowait()
                    self._total_dropped += 1
                except asyncio.QueueEmpty:
                    pass
            try:
                await asyncio.wait_for(q.put(payload), timeout=0.5)
                self._total_pushed += 1
                self._track_event_id(session_id, payload.id)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                self._total_dropped += 1

    async def stream(self, session_id: str, last_event_id: str | None = None):
        q = self.subscribe(session_id)
        try:
            yield SSEEvent("connected", {"session": session_id, "time": time.time()}).serialize()
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30.0)
                    self._track_get(session_id)
                    if last_event_id and payload.id <= last_event_id:
                        continue
                    yield payload.serialize()
                except asyncio.TimeoutError:
                    yield SSEEvent("ping", {"time": time.time()}).serialize()
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(session_id)

    def start_cleanup(self, idle_timeout: float = 300.0):
        async def _cleanup():
            while True:
                await asyncio.sleep(self._cleanup_interval)
                now = time.time()
                stale = [
                    sid for sid, info in list(self._sessions.items())
                    if now - info.last_get > idle_timeout and sid in self._queues and self._queues[sid].empty()
                ]
                for sid in stale:
                    logger.debug("SSE cleanup: removing stale session {}", sid)
                    self.unsubscribe(sid)

        self._task = asyncio.create_task(_cleanup())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None
        self._queues.clear()
        self._sessions.clear()


sse_stream = SSEStream()
