from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from raven.core.models import IncomingMessage, Message

MessageHandler = Callable[[IncomingMessage], Awaitable[None]]


class BaseChannel(ABC):
    channel_id: str = ""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def send(self, session_id: str, message: Message) -> None: ...

    @abstractmethod
    async def on_message(self, handler: MessageHandler) -> None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    async def health_check(self) -> bool:
        return True
