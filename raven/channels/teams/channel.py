from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage


class TeamsChannel(BaseChannel):
    channel_id = "teams"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        self._ready = True
        logger.info("Microsoft Teams channel started (webhook-based)")

    async def stop(self):
        self._ready = False
        logger.info("Microsoft Teams channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        text = body.get("text", "")
        from_id = body.get("from", {}).get("id", "") or body.get("user", {}).get("id", "")
        conversation = body.get("conversation", {}).get("id", "")
        if not text or not from_id:
            return False
        msg = IncomingMessage(
            channel="teams",
            user_id=from_id,
            session_id=f"teams:{conversation}:{from_id}",
            text=text,
            metadata={"conversation_id": conversation},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        logger.debug("Teams send stub: {}", message.content[:60])
