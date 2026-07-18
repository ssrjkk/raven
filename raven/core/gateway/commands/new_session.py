from __future__ import annotations

from uuid import uuid4

from raven.core.gateway.commands.base import CommandContext, CommandHandler


class NewSessionCommand(CommandHandler):
    name = "new"
    description = "Start a new session"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        new_sid = f"{ctx.event.channel}:{ctx.event.user_id}:{uuid4().hex[:8]}"
        await gateway.db.get_or_create_session(new_sid, ctx.event.channel, ctx.event.user_id)
        await gateway._send(ctx.event.channel, new_sid, "Starting fresh conversation.")
        return True
