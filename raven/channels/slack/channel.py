from __future__ import annotations
from typing import Callable, Awaitable
from uuid import uuid4
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage
from raven.core.config import settings

try:
    from slack_sdk.web.async_client import AsyncWebClient as _SlackClient
    from slack_sdk.errors import SlackApiError
    HAS_SLACK = True
except ImportError:
    _SlackClient = None
    SlackApiError = Exception
    HAS_SLACK = False


class SlackChannel(BaseChannel):
    channel_id = "slack"

    def __init__(self):
        self._token = settings.slack_bot_token
        self._signing_secret = settings.slack_signing_secret
        self._client: _SlackClient | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        if not HAS_SLACK:
            logger.warning("slack-sdk not installed, skipping Slack channel")
            return
        if not self._token:
            logger.warning("Slack token not configured, skipping")
            return
        self._client = _SlackClient(token=self._token)
        self._ready = True
        logger.info("Slack channel started")

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.close()
        logger.info("Slack channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_event(self, event: dict, team_id: str | None = None):
        """Handle an incoming Slack event. Args: event (dict): Slack event payload, team_id (str): Slack team ID"""
        if not self._handler:
            return
        event_type = event.get("type")
        if event_type == "message":
            subtype = event.get("subtype", "")
            if subtype in ("bot_message", "message_changed", "message_deleted"):
                return
            user_id = event.get("user", "")
            channel_id = event.get("channel", "")
            text = event.get("text", "")
            if not user_id or not text:
                return
            thread_ts = event.get("thread_ts", event.get("ts", ""))
            if self._handler:
                msg = IncomingMessage(
                    channel="slack",
                    user_id=user_id,
                    session_id=f"slack:{channel_id}:{user_id}",
                    text=text,
                    metadata={
                        "channel_id": channel_id,
                        "team_id": team_id or "",
                        "thread_ts": thread_ts,
                        "event_ts": event.get("ts", ""),
                    },
                )
                await self._handler(msg)

    async def send(self, session_id: str, message: Message):
        if not self._client or not self._ready:
            return
        parts = session_id.split(":")
        channel_id = parts[1] if len(parts) >= 2 else None
        if not channel_id:
            return
        try:
            kwargs = {"channel": channel_id, "text": message.content[:3000]}
            if len(parts) > 2:
                # thread_ts in session_id[2]
                kwargs["thread_ts"] = parts[2]
            await self._client.chat_postMessage(**kwargs)
        except SlackApiError as e:
            logger.error("Slack send failed: {}", e)
