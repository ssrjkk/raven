from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from loguru import logger

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
        """Ask the user to approve an action and return their decision.

        The default denies: a channel that has not implemented a prompt cannot report an approval
        it never received. Telegram and Discord override this with an interactive prompt.
        """
        logger.warning(
            "Channel '{}' has no confirmation prompt, denying: {}",
            self.channel_id or type(self).__name__,
            action_description,
        )
        return False
