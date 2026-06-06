from __future__ import annotations

import json

from loguru import logger
from typing import Any

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class FeishuChannel(EnterpriseChannel):
    channel_id = "feishu"

    async def _start(self):
        self._webhook_url = settings.feishu_webhook_url or ""
        self._app_id = settings.feishu_app_id or ""
        self._app_secret = settings.feishu_app_secret or ""
        self._tenant_token = ""
        self._token_expires = 0.0
        if self._app_id and self._app_secret:
            await self._refresh_token()

    async def _stop(self):
        pass

    async def _refresh_token(self):
        import httpx

        try:
            async with httpx.AsyncClient(base_url="https://open.feishu.cn", timeout=10) as client:
                resp = await client.post(
                    "/open-apis/auth/v3/tenant_access_token/internal",
                    json={"app_id": self._app_id, "app_secret": self._app_secret},
                )
                data = resp.json()
                self._tenant_token = data.get("tenant_access_token", "")
                expires_in = data.get("expire", 3600)
                self._token_expires = __import__("time").time() + expires_in - 60
        except Exception as e:
            logger.error("[feishu] token refresh failed: {}", e)

    async def _ensure_token(self):
        if self._app_id and self._app_secret and __import__("time").time() > self._token_expires:
            await self._refresh_token()

    async def handle_webhook(self, body: dict[str, Any]) -> bool:
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
        self._stats["received"] += 1
        await self._handler(
            IncomingMessage(
                channel="feishu",
                user_id=sender,
                session_id=f"feishu:{sender}",
                text=text,
                metadata={"event": body.get("header", {}).get("event_id", "")},
            )
        )
        return True

    async def _send_message(self, session_id: str, message: Message):
        if self._webhook_url:
            await self._post(self._webhook_url, json={"content": json.dumps({"text": message.content[:4000]})})
            return
        await self._ensure_token()
        if not self._tenant_token:
            return
        parts = session_id.split(":")
        user_id = parts[1] if len(parts) >= 2 else None
        if not user_id:
            return
        import httpx

        async with httpx.AsyncClient(base_url="https://open.feishu.cn", timeout=15) as client:
            resp = await client.post(
                "/open-apis/im/v1/messages",
                headers={"Authorization": f"Bearer {self._tenant_token}"},
                json={
                    "receive_id": user_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": message.content[:4000]}),
                },
            )
            resp.raise_for_status()
