from __future__ import annotations

import json
import time
from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.channel_config import get_channel_config
from raven.core.http_client import client_manager
from raven.core.models import IncomingMessage, Message


class FeishuChannel(EnterpriseChannel):
    channel_id = "feishu"

    async def _start(self):
        cfg = get_channel_config("feishu")
        self._webhook_url = cfg.get("webhook_url", "")
        self._app_id = cfg.get("app_id", "")
        self._app_secret = cfg.get("app_secret", "")
        self._tenant_token = ""
        self._token_expires = 0.0
        if self._app_id and self._app_secret:
            await self._refresh_token()

    async def _stop(self):
        self._webhook_url = ""
        self._app_id = ""
        self._app_secret = ""
        self._tenant_token = ""
        self._token_expires = 0.0
        logger.info("[feishu] channel stopped")

    async def _refresh_token(self):
        try:
            data = await client_manager.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
                timeout=10,
            )
            self._tenant_token = data.get("tenant_access_token", "")
            expires_in = data.get("expire", 3600)
            self._token_expires = time.time() + expires_in - 60
        except Exception as e:
            logger.error("[feishu] token refresh failed: {}", e)

    async def _ensure_token(self):
        if self._app_id and self._app_secret and time.time() > self._token_expires:
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
        try:
            await client_manager.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                headers={"Authorization": f"Bearer {self._tenant_token}"},
                json={
                    "receive_id": user_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": message.content[:4000]}),
                },
                timeout=15,
            )
        except Exception as e:
            logger.error("[feishu] send failed: {}", e)
