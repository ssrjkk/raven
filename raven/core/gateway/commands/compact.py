from __future__ import annotations

from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.security.sandbox_policy import MAIN_SESSION_POLICY, check_tool_allowed, get_policy_for_channel


class CompactCommand(CommandHandler):
    name = "compact"
    description = "Compact memory into summary"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        policy = get_policy_for_channel(ctx.event.channel)
        if policy is not MAIN_SESSION_POLICY:
            allowed, msg = check_tool_allowed(policy, "read", ctx.event.channel)
            if not allowed:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Access denied: {msg}")
                return True
        session_id = ctx.event.session_id or f"{ctx.event.channel}:{ctx.event.user_id}:default"
        session = await gateway.db.get_or_create_session(session_id, ctx.event.channel, ctx.event.user_id)
        agent = gateway.registry.create_agent(session)
        msgs = await gateway.db.get_session_messages(session.id, limit=100)
        if not msgs:
            await gateway._send(ctx.event.channel, ctx.event.session_id, "No messages to compact.")
            return True
        history_text = "\n".join(f"{m.role}: {m.content[:200]}" for m in msgs)
        summary = ""
        async for token in agent.simple_complete(
            [
                {"role": "system", "content": "Summarize this conversation concisely in 2-3 sentences."},
                {"role": "user", "content": f"Summarize:\n{history_text}"},
            ]
        ):
            summary += token
        if summary.strip():
            await gateway.db.replace_session_messages(
                session.id, [{"role": "system", "content": f"[Session compacted: {summary[:500]}]"}]
            )
        await gateway._send(ctx.event.channel, ctx.event.session_id, f"Session compacted.\nSummary: {summary[:300]}")
        return True
