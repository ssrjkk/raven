from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage


class LINECChannel(BaseChannel):
    channel_id = "line"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        self._ready = True
        logger.info("LINE channel started (webhook-based)")

    async def stop(self):
        self._ready = False
        logger.info("LINE channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        events = body.get("events", [])
        for ev in events:
            if ev.get("type") == "message":
                source = ev.get("source", {})
                user_id = source.get("userId", "")
                message = ev.get("message", {})
                msg_type = message.get("type", "")
                if msg_type == "text":
                    text = message.get("text", "")
                    if user_id and text:
                        msg = IncomingMessage(
                            channel="line",
                            user_id=user_id,
                            session_id=f"line:{user_id}",
                            text=text,
                            metadata={"reply_token": ev.get("replyToken", "")},
                        )
                        await self._handler(msg)
                        return True
        return False

    async def send(self, session_id: str, message: Message):
        logger.debug("LINE send stub: {}", message.content[:60])
