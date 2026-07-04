from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from raven.channels.base import BaseChannel
from raven.core.audit import AuditEventType, audit_logger
from raven.core.http_client import client_manager
from raven.core.metrics import metrics
from raven.core.models import IncomingMessage, Message


class RateLimiter:
    def __init__(self, max_per_minute: int = 30):
        self._max = max_per_minute
        self._tokens = float(max_per_minute)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        await self._lock.acquire()
        try:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(float(self._max), self._tokens + elapsed * (self._max / 60.0))
            self._last_refill = now
            if self._tokens < 1:
                wait = (1 - self._tokens) * (60.0 / self._max)
                self._lock.release()
                await asyncio.sleep(wait)
                await self._lock.acquire()
                self._tokens -= 1
            else:
                self._tokens -= 1
        finally:
            self._lock.release()


class EnterpriseChannel(BaseChannel):
    channel_id: str = ""

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False
        self._lock = asyncio.Lock()
        self._rate_limiter = RateLimiter(max_per_minute=30)
        self._stats = {"sent": 0, "failed": 0, "received": 0, "reconnects": 0}
        self._client = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @abstractmethod
    async def _start(self): ...

    @abstractmethod
    async def _stop(self): ...

    @abstractmethod
    async def _send_message(self, session_id: str, message: Message): ...

    async def start(self):
        self._loop = asyncio.get_running_loop()
        async with self._lock:
            await self._start()
            self._ready = True
            logger.info("[{}] Channel started", self.channel_id)

    async def stop(self):
        async with self._lock:
            if not self._ready:
                return
            self._ready = False
            await self._stop()
            logger.info("[{}] Channel stopped", self.channel_id)

    async def connect(self):
        await self.start()

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def send(self, session_id: str, message: Message):
        if not self._ready:
            logger.debug("[{}] send skipped: not ready", self.channel_id)
            return
        await self._rate_limiter.acquire()
        try:
            await self._send_message(session_id, message)
            self._stats["sent"] += 1
        except Exception as e:
            self._stats["failed"] += 1
            logger.error("[{}] send failed: {}", self.channel_id, e)

    async def health_check(self) -> bool:
        return self._ready

    def stats(self) -> dict[str, Any]:
        return {**self._stats, "channel": self.channel_id}

    async def _post(
        self, url: str, json: dict[str, Any], headers: dict[str, Any] | None = None, timeout: float = 15.0
    ) -> dict[str, Any]:
        return await client_manager.post(url, json=json, headers=headers or {}, timeout=timeout)

    async def _retry_call(self, fn, max_retries: int = 3, base_delay: float = 1.0):
        last_ex = None
        for attempt in range(max_retries):
            try:
                return await fn()
            except Exception as e:
                last_ex = e
                if attempt < max_retries - 1:
                    wait = base_delay * (2**attempt)
                    logger.warning("[{}] retry {}/{} after {}s: {}", self.channel_id, attempt + 1, max_retries, wait, e)
                    await asyncio.sleep(wait)
        if last_ex is not None:
            raise last_ex
        raise RuntimeError("Unreachable: retry loop completed without exception")

    async def _audit_send(self, session_id: str, message: Message):
        user_id = session_id.split(":")[1] if ":" in session_id else session_id
        await audit_logger.log(
            AuditEventType.MESSAGE_SENT,
            f"channel:{self.channel_id}",
            user_id,
            detail={"length": len(message.content)},
            channel=self.channel_id,
        )
        metrics.inc(f"channel.{self.channel_id}.sent", {"channel": self.channel_id})

    async def _audit_receive(self, user_id: str, text: str):
        await audit_logger.log(
            AuditEventType.MESSAGE_RECEIVED,
            user_id,
            f"channel:{self.channel_id}",
            detail={"length": len(text)},
            channel=self.channel_id,
        )
        metrics.inc(f"channel.{self.channel_id}.received", {"channel": self.channel_id})
