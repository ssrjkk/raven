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


class MatrixChannel(BaseChannel):
    channel_id = "matrix"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._homeserver = settings.matrix_homeserver or "https://matrix.org"
        self._access_token: str = ""
        self._user_id: str = ""
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, Matrix channel unavailable")
            return
        self._client = httpx.AsyncClient(base_url=self._homeserver, timeout=10)
        self._ready = True
        logger.info("Matrix channel started (homeserver: {})", self._homeserver)

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
        logger.info("Matrix channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        event = body.get("event", {})
        content = event.get("content", {})
        event_type = event.get("type", "")
        sender = event.get("sender", "")
        room_id = event.get("room_id", "")

        if event_type != "m.room.message" or not sender or not room_id:
            return False

        msg_type = content.get("msgtype", "")
        body_text = content.get("body", "")
        if msg_type != "m.text" or not body_text:
            return False

        msg = IncomingMessage(
            channel="matrix",
            user_id=sender,
            session_id=f"matrix:{room_id}:{sender}",
            text=body_text,
            metadata={"room_id": room_id, "event_id": event.get("event_id", "")},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        if not self._client or not self._ready:
            return
        parts = session_id.split(":")
        room_id = parts[1] if len(parts) >= 2 else None
        if not room_id:
            return
        try:
            resp = await self._client.put(
                f"/_matrix/client/v3/rooms/{room_id}/send/m.room.message",
                json={
                    "msgtype": "m.text",
                    "body": message.content[:3000],
                },
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("Matrix send failed: {}", e)
