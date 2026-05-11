from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage

try:
    from signal_cli import SignalAPI
    HAS_SIGNAL = True
except ImportError:
    HAS_SIGNAL = False


class SignalChannel(BaseChannel):
    channel_id = "signal"

    def __init__(self):
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._cli: str = ""
        self._ready = False

    async def start(self):
        if not HAS_SIGNAL:
            logger.warning("signal-cli not installed, Signal channel unavailable")
            return
        self._ready = True
        logger.info("Signal channel started")

    async def stop(self):
        self._ready = False
        logger.info("Signal channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def handle_webhook(self, body: dict) -> bool:
        if not self._handler or not self._ready:
            return False
        envelope = body.get("envelope", {})
        data_message = envelope.get("dataMessage", {}) or envelope.get("syncMessage", {}).get("sentMessage", {})
        source = envelope.get("source", "") or data_message.get("source", "")
        text = data_message.get("message", "")
        if not source or not text:
            return False
        msg = IncomingMessage(
            channel="signal",
            user_id=source,
            session_id=f"signal:{source}",
            text=text,
            metadata={"source": source},
        )
        await self._handler(msg)
        return True

    async def send(self, session_id: str, message: Message):
        logger.debug("Signal send stub: {}", message.content[:60])
