from __future__ import annotations

from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.channel_config import get_channel_config
from raven.core.models import IncomingMessage, Message


class WhatsAppChannel(EnterpriseChannel):
    channel_id = "whatsapp"

    async def _start(self):
        self._token = get_channel_config("whatsapp").get("token", "")
        self._phone_id = get_channel_config("whatsapp").get("phone_id", "")

    async def _stop(self):
        self._token = ""
        self._phone_id = ""
        logger.info("[whatsapp] channel stopped")

    async def handle_webhook(self, body: dict[str, Any]) -> bool:
        if not self._handler or not self._ready:
            return False
        handled = False
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") == "text":
                        from_id = msg.get("from", "")
                        text = msg["text"].get("body", "")
                        if from_id and text:
                            self._stats["received"] += 1
                            await self._handler(
                                IncomingMessage(
                                    channel="whatsapp",
                                    user_id=from_id,
                                    session_id=f"whatsapp:{from_id}",
                                    text=text,
                                    metadata={"msg_id": msg.get("id", ""), "from": from_id},
                                )
                            )
                            handled = True
        return handled

    async def _send_message(self, session_id: str, message: Message):
        if not self._token or not self._phone_id:
            return
        parts = session_id.split(":")
        to = parts[1] if len(parts) >= 2 else None
        if not to:
            return
        await self._post(
            f"https://graph.facebook.com/v18.0/{self._phone_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": message.content[:4000]},
            },
            headers={"Authorization": f"Bearer {self._token}"},
        )
