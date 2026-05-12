from __future__ import annotations

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class TeamsChannel(EnterpriseChannel):
    channel_id = "teams"

    async def _start(self):
        self._webhook_url = settings.teams_webhook_url or ""

    async def _stop(self):
        pass

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        text = body.get("text", "")
        from_id = body.get("from", {}).get("id", "") or body.get("user", {}).get("id", "")
        conversation = body.get("conversation", {}).get("id", "")
        if not text or not from_id:
            return False
        self._stats["received"] += 1
        await self._handler(IncomingMessage(
            channel="teams",
            user_id=from_id,
            session_id=f"teams:{conversation}:{from_id}",
            text=text,
            metadata={"conversation_id": conversation},
        ))
        return True

    async def _send_message(self, session_id: str, message: Message):
        if self._webhook_url:
            await self._post(self._webhook_url, json={"text": message.content[:4000]})
            return
        parts = session_id.split(":")
        conversation = parts[1] if len(parts) >= 2 else None
        if not conversation:
            return
        await self._post(
            f"https://api.teams.microsoft.com/v1/conversations/{conversation}/messages",
            json={"body": {"content": message.content[:4000]}},
        )
