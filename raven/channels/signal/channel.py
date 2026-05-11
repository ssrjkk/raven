from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage
from raven.core.config import settings

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class SignalChannel(BaseChannel):
    channel_id = "signal"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._api_url = settings.signal_api_url or "http://localhost:8080"
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, Signal channel unavailable")
            return
        self._client = httpx.AsyncClient(base_url=self._api_url, timeout=15)
        self._ready = True
        logger.info("Signal channel started (API: {})", self._api_url)

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
        logger.info("Signal channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        envelope = body.get("envelope", {})
        data_message = envelope.get("dataMessage", {}) or envelope.get("syncMessage", {}).get("sentMessage", {})
        source = envelope.get("source", "") or data_message.get("source", "")
        text = data_message.get("message", "")
        if not source or not text:
            return False
        msg = IncomingMessage(
            channel="signal",
            user_id=source,
            session_id=f"signal:{source}",
            text=text,
            metadata={"source": source},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        if not self._client or not self._ready:
            return
        parts = session_id.split(":")
        recipient = parts[1] if len(parts) >= 2 else None
        if not recipient:
            return
        try:
            resp = await self._client.post(
                "/v2/send",
                json={
                    "message": message.content[:3000],
                    "recipient": recipient,
                },
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("Signal send failed: {}", e)
