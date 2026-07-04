from __future__ import annotations

from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class GoogleChatChannel(EnterpriseChannel):
    channel_id = "googlechat"

    async def _start(self):
        self._webhook_url = settings.googlechat_webhook_url or ""

    async def _stop(self):
        logger.info("[googlechat] channel stopped")

    async def handle_webhook(self, body: dict[str, Any]) -> bool:
        if not self._handler or not self._ready:
            return False
        message = body.get("message", {})
        sender = message.get("sender", {})
        text = message.get("text", "")
        space = body.get("space", {}).get("name", "")
        user_id = sender.get("name", "") or sender.get("email", "")
        if not text or not user_id:
            return False
        self._stats["received"] += 1
        await self._handler(
            IncomingMessage(
                channel="googlechat",
                user_id=user_id,
                session_id=f"googlechat:{space}:{user_id}",
                text=text,
                metadata={"space": space},
            )
        )
        return True

    async def _send_message(self, session_id: str, message: Message):
        parts = session_id.split(":")
        space = parts[1] if len(parts) >= 2 else None
        if not space and not self._webhook_url:
            return
        url = self._webhook_url or f"https://chat.googleapis.com/v1/spaces/{space}/messages"
        await self._post(url, json={"text": message.content[:4000]})
