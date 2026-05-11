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


class LINECChannel(BaseChannel):
    channel_id = "line"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._token = settings.line_channel_token or ""
        self._secret = settings.line_channel_secret or ""
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, LINE unavailable")
            return
        self._client = httpx.AsyncClient(base_url="https://api.line.me", timeout=15)
        self._ready = True
        logger.info("LINE channel started")

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
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
        if not self._client or not self._ready or not self._token:
            return
        parts = session_id.split(":")
        to = parts[1] if len(parts) >= 2 else None
        if not to:
            return
        try:
            resp = await self._client.post(
                "/v2/bot/message/push",
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "to": to,
                    "messages": [{"type": "text", "text": message.content[:5000]}],
                },
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("LINE send failed: {}", e)
