from __future__ import annotations

from typing import Any

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class SignalChannel(EnterpriseChannel):
    channel_id = "signal"
    DEFAULT_SIGNAL_URL = "http://localhost:8080"

    async def _start(self):
        self._api_url = settings.signal_api_url or self.DEFAULT_SIGNAL_URL
        self._client = None

    async def _stop(self):
        self._client = None

    async def handle_webhook(self, body: dict[str, Any]) -> bool:
        if not self._handler or not self._ready:
            return False
        envelope = body.get("envelope", {})
        data = envelope.get("dataMessage", {}) or envelope.get("syncMessage", {}).get("sentMessage", {})
        source = envelope.get("source", "") or data.get("source", "")
        text = data.get("message", "")
        if not source or not text:
            return False
        self._stats["received"] += 1
        await self._handler(
            IncomingMessage(
                channel="signal",
                user_id=source,
                session_id=f"signal:{source}",
                text=text,
                metadata={"source": source},
            )
        )
        return True

    async def _send_message(self, session_id: str, message: Message):
        parts = session_id.split(":")
        recipient = parts[1] if len(parts) >= 2 else None
        if not recipient:
            return
        import httpx

        async with httpx.AsyncClient(base_url=self._api_url, timeout=15) as client:
            resp = await client.post("/v2/send", json={"message": message.content[:3000], "recipient": recipient})
            resp.raise_for_status()
