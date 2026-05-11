from __future__ import annotations
import json
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


class FeishuChannel(BaseChannel):
    channel_id = "feishu"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._client: httpx.AsyncClient | None = None
        self._webhook_url = settings.feishu_webhook_url or ""
        self._app_id = settings.feishu_app_id or ""
        self._app_secret = settings.feishu_app_secret or ""
        self._tenant_token = ""
        self._ready = False

    async def start(self):
        if not HAS_HTTPX:
            logger.warning("httpx not installed, Feishu unavailable")
            return
        self._client = httpx.AsyncClient(base_url="https://open.feishu.cn", timeout=15)
        self._ready = True
        await self._refresh_token()
        logger.info("Feishu/Lark channel started")

    async def stop(self):
        self._ready = False
        if self._client:
            await self._client.aclose()
        logger.info("Feishu channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def _refresh_token(self):
        if not self._app_id or not self._app_secret:
            return
        try:
            resp = await self._client.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
            )
            data = resp.json()
            self._tenant_token = data.get("tenant_access_token", "")
        except Exception as e:
            logger.error("Feishu token refresh failed: {}", e)

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        event = body.get("event", {}) or body.get("header", {})
        sender = event.get("sender", {}).get("sender_id", {}).get("user_id", "")
        text = ""
        message = event.get("message", {})
        if message:
            content = message.get("content", "")
            try:
                content_dict = json.loads(content) if isinstance(content, str) else content
                text = content_dict.get("text", "")
            except (json.JSONDecodeError, AttributeError):
                text = str(content)[:500]
        if not sender or not text:
            return False
        msg = IncomingMessage(
            channel="feishu",
            user_id=sender,
            session_id=f"feishu:{sender}",
            text=text,
            metadata={"event": body.get("header", {}).get("event_id", "")},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        if not self._client or not self._ready:
            return
        if self._webhook_url:
            try:
                resp = await self._client.post(self._webhook_url, json={"content": json.dumps({"text": message.content[:4000]})})
                resp.raise_for_status()
            except Exception as e:
                logger.error("Feishu webhook send failed: {}", e)
            return
        if not self._tenant_token:
            return
        parts = session_id.split(":")
        user_id = parts[1] if len(parts) >= 2 else None
        if not user_id:
            return
        try:
            resp = await self._client.post(
                "/open-apis/im/v1/messages",
                headers={"Authorization": f"Bearer {self._tenant_token}"},
                json={
                    "receive_id": user_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": message.content[:4000]}),
                },
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("Feishu send failed: {}", e)
