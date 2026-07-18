from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.skills import skills_registry


class StatusCommand(CommandHandler):
    name = "status"
    description = "Show system status"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        channel_ids = await gateway.channels.list_ids()
        await gateway._send(
            ctx.event.channel,
            ctx.event.session_id,
            f"Raven AI is running.\nChannels: {', '.join(channel_ids)}\n"
            f"Agents: {len(gateway.registry.list_agents())}\n"
            f"Skills: {len(skills_registry.list_names())}",
        )
        return True
