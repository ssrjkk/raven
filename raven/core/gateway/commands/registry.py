from __future__ import annotations

from collections.abc import Iterable

from raven.core.gateway.commands.base import CommandContext, CommandHandler


class CommandRegistry:
    def __init__(self):
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, handler: CommandHandler) -> None:
        self._handlers[handler.name] = handler

    def get(self, name: str) -> CommandHandler | None:
        return self._handlers.get(name)

    async def execute(self, command_name: str, ctx: CommandContext) -> bool:
        handler = self._handlers.get(command_name)
        if handler is None:
            return False
        return await handler.execute(ctx)

    def list_commands(self) -> Iterable[CommandHandler]:
        return self._handlers.values()
