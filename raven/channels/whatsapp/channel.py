from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage
from raven.core.config import settings


class WhatsAppChannel(BaseChannel):
    channel_id = "whatsapp"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        self._ready = True
        logger.info("WhatsApp channel started (webhook-based)")

    async def stop(self):
        self._ready = False
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
        return True

    async def send(self, session_id: str, message: Message):
        logger.debug("WhatsApp send stub for session {}: {}", session_id, message.content[:80])
