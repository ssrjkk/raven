from __future__ import annotations

import asyncio

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class MatrixChannel(EnterpriseChannel):
    channel_id = "matrix"

    async def _start(self):
        self._homeserver = settings.matrix_homeserver.rstrip("/") if settings.matrix_homeserver else ""
        self._token = settings.matrix_access_token or ""
        self._sync_token = ""
        self._sync_task: asyncio.Task | None = None
        self._rooms: dict[str, str] = {}

    async def _stop(self):
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None

    async def _matrix_get(self, path: str):
        import httpx
        async with httpx.AsyncClient(base_url=self._homeserver, timeout=15) as client:
            resp = await client.get(path, headers={"Authorization": f"Bearer {self._token}"})
            resp.raise_for_status()
            return resp.json()

    async def _matrix_post(self, path: str, json_body: dict):
        import httpx
        async with httpx.AsyncClient(base_url=self._homeserver, timeout=15) as client:
            resp = await client.post(path, json=json_body, headers={"Authorization": f"Bearer {self._token}"})
            resp.raise_for_status()
            return resp.json()

    async def _start_sync(self):
        if not self._homeserver or not self._token:
            return
        try:
            resp = await self._matrix_get("/_matrix/client/v3/account/whoami")
            logger.info("[matrix] authenticated as {}", resp.get("user_id", "?"))
        except Exception as e:
            logger.error("[matrix] auth check failed: {}", e)
            return
        self._sync_task = asyncio.create_task(self._sync_loop())

    async def _sync_loop(self):
        while self._ready:
            try:
                params = "?timeout=30000"
                if self._sync_token:
                    params += f"&since={self._sync_token}"
                data = await self._matrix_get(f"/_matrix/client/v3/sync{params}")
                self._sync_token = data.get("next_batch", self._sync_token)
                for room_id, room_data in data.get("rooms", {}).get("join", {}).items():
                    await self._handle_room_events(room_id, room_data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._ready:
                    logger.warning("[matrix] sync error: {} — reconnecting", e)
                    self._stats["reconnects"] += 1
                    await asyncio.sleep(5)

    async def _handle_room_events(self, room_id: str, room_data: dict):
        for event in room_data.get("timeline", {}).get("events", []):
            if event.get("type") == "m.room.message" and event.get("content", {}).get("msgtype") == "m.text":
                sender = event.get("sender", "")
                body = event.get("content", {}).get("body", "")
                if sender and body and self._handler:
                    self._stats["received"] += 1
                    await self._handler(IncomingMessage(
                        channel="matrix",
                        user_id=sender,
                        session_id=f"matrix:{room_id}:{sender}",
                        text=body,
                        metadata={"room_id": room_id, "event_id": event.get("event_id", "")},
                    ))

    async def handle_event(self, event: dict, room_id: str):
        if not self._handler or not self._ready:
            return
        if event.get("type") == "m.room.message" and event.get("content", {}).get("msgtype") == "m.text":
            sender = event.get("sender", "")
            body = event.get("content", {}).get("body", "")
            if sender and body:
                self._stats["received"] += 1
                await self._handler(IncomingMessage(
                    channel="matrix",
                    user_id=sender,
                    session_id=f"matrix:{room_id}:{sender}",
                    text=body,
                    metadata={"room_id": room_id, "event_id": event.get("event_id", "")},
                ))
                return True
        return False

    async def _send_message(self, session_id: str, message: Message):
        if not self._homeserver or not self._token:
            return
        parts = session_id.split(":")
        room_id = parts[1] if len(parts) >= 2 else None
        if not room_id:
            return
        await self._matrix_post(f"/_matrix/client/v3/rooms/{room_id}/send/m.room.message", {
            "msgtype": "m.text",
            "body": message.content[:4000],
        })
