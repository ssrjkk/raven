from __future__ import annotations

from typing import Any

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class LINECChannel(EnterpriseChannel):
    channel_id = "line"

    async def _start(self):
        self._token = settings.line_channel_token or ""
        self._secret = settings.line_channel_secret or ""

    async def _stop(self):
        pass

    async def handle_webhook(self, body: dict[str, Any]) -> bool:
        if not self._handler or not self._ready:
            return False
        for ev in body.get("events", []):
            if ev.get("type") == "message":
                source = ev.get("source", {})
                user_id = source.get("userId", "")
                message = ev.get("message", {})
                if message.get("type") == "text":
                    text = message.get("text", "")
                    if user_id and text:
                        self._stats["received"] += 1
                        await self._handler(
                            IncomingMessage(
                                channel="line",
                                user_id=user_id,
                                session_id=f"line:{user_id}",
                                text=text,
                                metadata={"reply_token": ev.get("replyToken", "")},
                            )
                        )
                        return True
        return False

    async def _send_message(self, session_id: str, message: Message):
        if not self._token:
            return
        parts = session_id.split(":")
        to = parts[1] if len(parts) >= 2 else None
        if not to:
            return
        await self._post(
            "https://api.line.me/v2/bot/message/push",
            json={"to": to, "messages": [{"type": "text", "text": message.content[:5000]}]},
            headers={"Authorization": f"Bearer {self._token}"},
        )
