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

    async def ask_confirmation(self, user_id: str, action_description: str, session_id: str = "") -> bool:
        """Ask user for confirmation before executing an action that requires approval.

        Default implementation auto-confirms (returns True).
        Channels that support interactive confirmation should override this
        to send a yes/no prompt to the user and return their decision.
        """
        return True
