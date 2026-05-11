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


class WhatsAppChannel(BaseChannel):
    channel_id = "whatsapp"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._token = settings.whatsapp_token or ""
        self._phone_id = settings.whatsapp_phone_id or ""
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, WhatsApp unavailable")
            return
        self._client = httpx.AsyncClient(timeout=15)
        self._ready = True
        logger.info("WhatsApp channel started")

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
        logger.info("WhatsApp channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        handled = False
        entry = body.get("entry", [])
        for e in entry:
            changes = e.get("changes", [])
            for c in changes:
                value = c.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    if msg.get("type") == "text":
                        from_id = msg.get("from", "")
                        text = msg["text"].get("body", "")
                        msg_id = msg.get("id", "")
                        if from_id and text:
                            event = IncomingMessage(
                                channel="whatsapp",
                                user_id=from_id,
                                session_id=f"whatsapp:{from_id}",
                                text=text,
                                metadata={"msg_id": msg_id, "from": from_id},
                            )
                            await self._handler(event)
                            handled = True
        return handled

    async def send(self, session_id: str, message: Message):
        if not self._client or not self._ready or not self._token or not self._phone_id:
            logger.debug("WhatsApp send skipped: missing config")
            return
        parts = session_id.split(":")
        to = parts[1] if len(parts) >= 2 else None
        if not to:
            return
        try:
            resp = await self._client.post(
                f"https://graph.facebook.com/v18.0/{self._phone_id}/messages",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": message.content[:4000]},
                },
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("WhatsApp send failed: {}", e)
