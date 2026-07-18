from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler


class ResetCommand(CommandHandler):
    name = "reset"
    description = "Reset session history"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        sid = ctx.event.session_id or f"{ctx.event.channel}:{ctx.event.user_id}:default"
        await gateway.db.delete_session(sid)
        await gateway._send(ctx.event.channel, sid, "Session reset.")
        return True
