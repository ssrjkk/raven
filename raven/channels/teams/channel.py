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


class TeamsChannel(BaseChannel):
    channel_id = "teams"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._webhook_url = settings.teams_webhook_url or ""
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, Teams unavailable")
            return
        self._client = httpx.AsyncClient(timeout=15)
        self._ready = True
        logger.info("Microsoft Teams channel started")

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
        logger.info("Teams channel stopped")

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
        if not self._client or not self._ready:
            return
        if self._webhook_url:
            try:
                resp = await self._client.post(
                    self._webhook_url,
                    json={"text": message.content[:4000]},
                )
                resp.raise_for_status()
            except Exception as e:
                logger.error("Teams send failed: {}", e)
            return
        parts = session_id.split(":")
        conversation = parts[1] if len(parts) >= 2 else None
        if not conversation:
            return
        try:
            resp = await self._client.post(
                f"https://api.teams.microsoft.com/v1/conversations/{conversation}/messages",
                json={"body": {"content": message.content[:4000]}},
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("Teams send failed: {}", e)
