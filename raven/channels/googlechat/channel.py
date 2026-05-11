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


class GoogleChatChannel(BaseChannel):
    channel_id = "googlechat"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._webhook_url = settings.googlechat_webhook_url or ""
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, Google Chat unavailable")
            return
        self._client = httpx.AsyncClient(timeout=15)
        self._ready = True
        logger.info("Google Chat channel started")

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
        logger.info("Google Chat channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        message = body.get("message", {})
        sender = message.get("sender", {})
        text = message.get("text", "")
        space = body.get("space", {}).get("name", "")
        user_id = sender.get("name", "") or sender.get("email", "")
        if not text or not user_id:
            return False
        msg = IncomingMessage(
            channel="googlechat",
            user_id=user_id,
            session_id=f"googlechat:{space}:{user_id}",
            text=text,
            metadata={"space": space},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        if not self._client or not self._ready:
            return
        parts = session_id.split(":")
        space = parts[1] if len(parts) >= 2 else None
        if not space:
            return
        url = self._webhook_url or f"https://chat.googleapis.com/v1/spaces/{space}/messages"
        try:
            resp = await self._client.post(url, json={"text": message.content[:4000]})
            resp.raise_for_status()
        except Exception as e:
            logger.error("Google Chat send failed: {}", e)
