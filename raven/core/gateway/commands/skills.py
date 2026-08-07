from __future__ import annotations

from loguru import logger

from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.skills import skills_registry


class SkillsCommand(CommandHandler):
    name = "skills"
    description = "List available skills"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        names = set(skills_registry.list_names())
        try:
            from raven.core.artifacts import get_artifact_manager

            root = getattr(gateway, "_artifact_root", None)
            if root is not None:
                names.update(index.name for index in get_artifact_manager(cwd=root).skills_index())
        except Exception as e:
            logger.debug("Artifact skills listing failed: {}", e)
        if names:
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Skills: {', '.join(sorted(names))}")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "No skills loaded.")
        return True
