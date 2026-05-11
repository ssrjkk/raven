from __future__ import annotations
import asyncio
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage

try:
    import irclib
    HAS_IRC = True
except ImportError:
    HAS_IRC = False


class IRCChannel(BaseChannel):
    channel_id = "irc"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._server = "irc.libera.chat"
        self._port = 6697
        self._nick = "raven-bot"
        self._channels: list[str] = []
        self._ready = False

    async def start(self):
        if not HAS_IRC:
            logger.warning("irclib not installed, IRC channel unavailable")
            return
        self._ready = True
        logger.info("IRC channel started: {}:{}/{}", self._server, self._port, self._nick)

    async def stop(self):
        self._ready = False
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
        logger.debug("IRC send stub: {}", message.content[:60])
