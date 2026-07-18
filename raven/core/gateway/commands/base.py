from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from raven.core.models import IncomingMessage


@dataclass
class CommandContext:
    event: IncomingMessage
    user: dict[str, Any]
    args: list[str]


class CommandHandler(ABC):
    def __init__(self, gateway: Any):
        self.gateway = gateway

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    async def execute(self, ctx: CommandContext) -> bool: ...
