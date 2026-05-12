from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from loguru import logger

from raven.channels.base import BaseChannel
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


class IRCChannel(BaseChannel):
    channel_id = "irc"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._server = settings.irc_server or "irc.libera.chat"
        self._port = settings.irc_port or 6697
        self._nick = settings.irc_nick or "raven-bot"
        self._password = settings.irc_password or ""
        self._channels: list[str] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ready = False

    async def start(self):
        self._ready = True
        logger.info("IRC channel started: {}:{}/{}", self._server, self._port, self._nick)

    async def stop(self):
        self._ready = False
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
        logger.info("IRC channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_message(self, nick: str, channel: str, text: str):
        if not self._handler or not self._ready:
            return
        if nick == self._nick:
            return
        msg = IncomingMessage(
            channel="irc",
            user_id=nick,
            session_id=f"irc:{channel}:{nick}",
            text=text,
            metadata={"channel": channel, "server": self._server},
        )
        await self._handler(msg)

    async def send(self, session_id: str, message: Message):
        if not self._ready:
            return
        parts = session_id.split(":")
        target = parts[1] if len(parts) >= 2 else None
        if not target:
            return
        text = message.content[:400].replace("\n", " ")
        if self._writer:
            try:
                self._writer.write(f"PRIVMSG {target} :{text}\r\n".encode())
                await self._writer.drain()
            except Exception as e:
                logger.error("IRC send failed: {}", e)
