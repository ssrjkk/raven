from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.gateway.commands.base import CommandContext, CommandHandler

if TYPE_CHECKING:
    from raven.core.gateway.commands.registry import CommandRegistry

# Pairing is approved inside the gateway's allowlist check, before the registry is consulted, so
# it has no handler that could list itself. The guard in tests/core/test_gateway_commands.py fails
# if a line here stops being dispatched.
EXTERNAL_COMMANDS = (("/pair <code>", "Authorize with pairing code"),)


def command_entries(registry: CommandRegistry) -> list[tuple[str, str]]:
    """One entry per command the gateway will actually accept, taken from the handlers themselves."""
    entries = [
        ("/" + handler.name + (f" {handler.usage}" if handler.usage else ""), handler.description)
        for handler in sorted(registry.list_commands(), key=lambda h: h.name)
    ]
    return entries + list(EXTERNAL_COMMANDS)


def help_body(registry: CommandRegistry) -> str:
    """What /help sends: the header, then one line per command."""
    lines = [f"{call} - {description}" for call, description in command_entries(registry)]
    return "\n".join(["Commands:", *lines])


class HelpCommand(CommandHandler):
    name = "help"
    description = "Show this help"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        await gateway._send(ctx.event.channel, ctx.event.session_id, help_body(gateway.commands))
        return True
