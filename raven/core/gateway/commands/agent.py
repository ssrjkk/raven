from __future__ import annotations

from typing import TYPE_CHECKING, Any

from raven.core.agents import PROFILES

if TYPE_CHECKING:
    pass

from raven.core.gateway.commands.base import CommandHandler


class AgentCommand(CommandHandler):
    def __init__(self, gateway: Any):
        self._gw = gateway

    @property
    def name(self) -> str:
        return "agent"

    @property
    def description(self) -> str:
        available = ", ".join(PROFILES.keys())
        return f"Switch agent profile: /agent <profile>  (available: {available})"

    async def execute(self, ctx: Any) -> bool:
        args = ctx.args
        if not args:
            profile_list = "\n".join(f"  /agent {k} — {v.display_name}" for k, v in PROFILES.items())
            await self._gw._send(
                ctx.event.channel, ctx.event.session_id,
                f"Available agent profiles:\n{profile_list}\n\nUsage: /agent <profile>",
            )
            return True
        profile_name = args[0].lower()
        if profile_name not in PROFILES:
            await self._gw._send(
                ctx.event.channel, ctx.event.session_id,
                f"Unknown profile: {profile_name}. Available: {', '.join(PROFILES.keys())}",
            )
            return True
        ctx.user["agent_profile"] = profile_name
        await self._gw._send(
            ctx.event.channel, ctx.event.session_id,
            f"Switched to agent profile: {PROFILES[profile_name].display_name}",
        )
        return True


class AgentStatusCommand(CommandHandler):
    def __init__(self, gateway: Any):
        self._gw = gateway

    @property
    def name(self) -> str:
        return "agent_status"

    @property
    def description(self) -> str:
        return "Show current agent profile and status"

    async def execute(self, ctx: Any) -> bool:
        profile = (ctx.user or {}).get("agent_profile", "auto")
        await self._gw._send(
            ctx.event.channel, ctx.event.session_id,
            f"Current agent mode: {profile}\n"
            f"Use /agent <name> to switch profiles.",
        )
        return True
