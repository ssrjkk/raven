from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage


class GoogleChatChannel(BaseChannel):
    channel_id = "googlechat"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        self._ready = True
        logger.info("Google Chat channel started (webhook-based)")

    async def stop(self):
        self._ready = False
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
        logger.debug("Google Chat send stub: {}", message.content[:60])
