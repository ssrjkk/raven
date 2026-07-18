from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.skills import skills_registry


class SkillsCommand(CommandHandler):
    name = "skills"
    description = "List available skills"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        names = skills_registry.list_names()
        if names:
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Skills: {', '.join(names)}")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "No skills loaded.")
        return True
