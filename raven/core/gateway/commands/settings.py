from __future__ import annotations

from uuid import uuid4

from raven.core.gateway.commands.base import CommandContext, CommandHandler


class ThinkCommand(CommandHandler):
    name = "think"
    description = "Set thinking level"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        level = ctx.args[0] if ctx.args else "high"
        if level in ("low", "medium", "high"):
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Thinking level set to: {level}.")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /think <low|medium|high>")
        return True


class VerboseCommand(CommandHandler):
    name = "verbose"
    description = "Toggle verbose mode"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        setting = ctx.args[0] if ctx.args else ""
        if setting in ("on", "off"):
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Verbose mode: {setting}.")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /verbose <on|off>")
        return True


class TraceCommand(CommandHandler):
    name = "trace"
    description = "Toggle trace mode"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        setting = ctx.args[0] if ctx.args else ""
        if setting in ("on", "off"):
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Trace mode: {setting}.")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /trace <on|off>")
        return True


class UsageCommand(CommandHandler):
    name = "usage"
    description = "Show usage stats"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        mode = ctx.args[0] if ctx.args else ""
        if mode in ("off", "tokens", "full"):
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Usage mode: {mode}.")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /usage <off|tokens|full>")
        return True


class RestartCommand(CommandHandler):
    name = "restart"
    description = "Restart the agent"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        new_session_id = f"{ctx.event.channel}:{ctx.event.user_id}:{uuid4().hex[:8]}"
        await gateway.db.get_or_create_session(new_session_id, ctx.event.channel, ctx.event.user_id)
        await gateway._send(ctx.event.channel, new_session_id, "Session restarted.")
        return True


class ActivationCommand(CommandHandler):
    name = "activation"
    description = "Show activation info"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        mode = ctx.args[0] if ctx.args else ""
        if mode in ("mention", "always"):
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Activation mode: {mode}.")
        else:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Usage: /activation <mention|always>")
        return True
