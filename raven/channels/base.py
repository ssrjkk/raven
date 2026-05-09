from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, Awaitable
from raven.core.models import Message, IncomingMessage

MessageHandler = Callable[[IncomingMessage], Awaitable[None]]


class BaseChannel(ABC):
    channel_id: str = ""

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def send(self, session_id: str, message: Message) -> None:
        ...

    @abstractmethod
    async def on_message(self, handler: MessageHandler) -> None:
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...
