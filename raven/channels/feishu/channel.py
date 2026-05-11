from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage


class FeishuChannel(BaseChannel):
    channel_id = "feishu"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        self._ready = True
        logger.info("Feishu/Lark channel started (webhook-based)")

    async def stop(self):
        self._ready = False
        logger.info("Feishu/Lark channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        event = body.get("event", {}) or body.get("header", {})
        sender = event.get("sender", {}).get("sender_id", {}).get("user_id", "")
        text = ""
        message = event.get("message", {})
        if message:
            content = message.get("content", "")
            import json
            try:
                content_dict = json.loads(content) if isinstance(content, str) else content
                text = content_dict.get("text", "")
            except (json.JSONDecodeError, AttributeError):
                text = str(content)[:500]
        if not sender or not text:
            return False
        msg = IncomingMessage(
            channel="feishu",
            user_id=sender,
            session_id=f"feishu:{sender}",
            text=text,
            metadata={"event": body.get("header", {}).get("event_id", "")},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        logger.debug("Feishu send stub: {}", message.content[:60])
