from __future__ import annotations

import hashlib
import hmac
from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message

try:
    from slack_sdk.errors import SlackApiError
    from slack_sdk.web.async_client import AsyncWebClient

    HAS_SLACK_SDK = True
except ImportError:
    HAS_SLACK_SDK = False


class SlackChannel(EnterpriseChannel):
    channel_id = "slack"

    async def _start(self):
        self._token = settings.slack_bot_token or ""
        self._signing_secret = settings.slack_signing_secret or ""
        if HAS_SLACK_SDK and self._token:
            self._client = AsyncWebClient(token=self._token)
        else:
            self._client = None

    async def _stop(self):
        self._client = None

    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        if not self._signing_secret:
            return True
        basestring = f"v0:{timestamp}:".encode() + body
        expected = "v0=" + hmac.new(self._signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def handle_event(self, event: dict[str, Any], team_id: str | None = None):
        if not self._handler or not self._ready:
            return
        msg_type = event.get("type", "")
        if msg_type == "message":
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")
            if user and text and not event.get("bot_id") and event.get("subtype") != "bot_message":
                self._stats["received"] += 1
                await self._handler(
                    IncomingMessage(
                        channel="slack",
                        user_id=user,
                        session_id=f"slack:{channel}:{user}",
                        text=text,
                        metadata={"channel": channel, "team_id": team_id or ""},
                    )
                )

    async def _send_message(self, session_id: str, message: Message):
        if not self._client:
            return
        parts = session_id.split(":")
        channel = parts[1] if len(parts) >= 2 else None
        if not channel:
            return
        try:
            await self._client.chat_postMessage(channel=channel, text=message.content[:4000])
        except SlackApiError as e:
            logger.error("[slack] send failed: {}", e)
