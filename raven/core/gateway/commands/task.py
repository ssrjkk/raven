from __future__ import annotations

from raven.core.auth import Permission
from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY, check_tool_allowed, get_policy_for_channel


class TaskCommand(CommandHandler):
    name = "task"
    description = "Run a task in background"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        policy = get_policy_for_channel(ctx.event.channel)
        if policy is not MAIN_SESSION_POLICY:
            allowed, msg = check_tool_allowed(policy, "gateway", ctx.event.channel)
            if not allowed:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Access denied: {msg}")
                return True
        if not gateway._check_permission(ctx.user, Permission.TASK_RUN):
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Access denied: insufficient permissions")
            return True
        goal = " ".join(ctx.args)
        if not goal:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /task <goal description>")
            return True
        await gateway._send(ctx.event.channel, ctx.event.session_id, f"Planning task: {goal[:100]}...")
        await gateway._bg_task(gateway.tasks.create_and_run(
            goal=goal,
            user_id=ctx.event.user_id,
            channel=ctx.event.channel,
            session_id=ctx.event.session_id or "",
        ))
        return True
