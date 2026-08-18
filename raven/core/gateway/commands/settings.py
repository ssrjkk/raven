from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler

_PREF_KEYS = ("think_level", "verbose", "trace", "usage_mode", "activation_mode")


class ThinkCommand(CommandHandler):
    name = "think"
    description = "Set thinking level"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        level = ctx.args[0] if ctx.args else ""
        if level in ("low", "medium", "high"):
            gateway.set_pref(ctx.event.channel, ctx.event.user_id, "think_level", level)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Thinking level set to: {level}.")
        else:
            current = gateway.get_pref(ctx.event.channel, ctx.event.user_id, "think_level", "high")
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"Thinking level: {current}.\nUsage: /think <low|medium|high>",
            )
        return True


class VerboseCommand(CommandHandler):
    name = "verbose"
    description = "Toggle verbose mode"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        setting = ctx.args[0] if ctx.args else ""
        if setting in ("on", "off"):
            gateway.set_pref(ctx.event.channel, ctx.event.user_id, "verbose", setting)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Verbose mode: {setting}.")
        else:
            current = gateway.get_pref(ctx.event.channel, ctx.event.user_id, "verbose", "off")
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"Verbose mode: {current}.\nUsage: /verbose <on|off>",
            )
        return True


class TraceCommand(CommandHandler):
    name = "trace"
    description = "Toggle trace mode"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        setting = ctx.args[0] if ctx.args else ""
        if setting in ("on", "off"):
            gateway.set_pref(ctx.event.channel, ctx.event.user_id, "trace", setting)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Trace mode: {setting}.")
        else:
            current = gateway.get_pref(ctx.event.channel, ctx.event.user_id, "trace", "off")
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"Trace mode: {current}.\nUsage: /trace <on|off>",
            )
        return True


class UsageCommand(CommandHandler):
    name = "usage"
    description = "Show usage stats"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        mode = ctx.args[0] if ctx.args else ""
        if mode in ("off", "tokens", "full"):
            gateway.set_pref(ctx.event.channel, ctx.event.user_id, "usage_mode", mode)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Usage mode: {mode}.")
        else:
            current = gateway.get_pref(ctx.event.channel, ctx.event.user_id, "usage_mode", "off")
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"Usage mode: {current}.\nUsage: /usage <off|tokens|full>",
            )
        return True


class RestartCommand(CommandHandler):
    name = "restart"
    description = "Restart the agent"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        sid = ctx.event.session_id or f"{ctx.event.channel}:{ctx.event.user_id}:default"
        await gateway.db.delete_session(sid)
        await gateway._send(ctx.event.channel, sid, "Session restarted.")
        return True


class ActivationCommand(CommandHandler):
    name = "activation"
    description = "Show activation info"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        mode = ctx.args[0] if ctx.args else ""
        if mode in ("mention", "always"):
            gateway.set_pref(ctx.event.channel, ctx.event.user_id, "activation_mode", mode)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Activation mode: {mode}.")
        else:
            current = gateway.get_pref(ctx.event.channel, ctx.event.user_id, "activation_mode", "mention")
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"Activation mode: {current}.\nUsage: /activation <mention|always>",
            )
        return True
