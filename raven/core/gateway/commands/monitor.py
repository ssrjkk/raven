from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.auth import Permission
from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.security.sandbox_policy import check_tool_allowed, get_policy_for_channel

if TYPE_CHECKING:
    pass


class MonitorCommand(CommandHandler):
    name = "monitor"
    description = "Monitor management"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        policy = get_policy_for_channel(ctx.event.channel)
        if policy is not None:
            allowed, msg = check_tool_allowed(policy, "read", ctx.event.channel)
            if not allowed:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Access denied: {msg}")
                return True
        if not gateway._check_permission(ctx.user, Permission.MONITOR_READ):
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Access denied: insufficient permissions")
            return True

        from raven.core.monitor.models import Monitor, MonitorStatus, MonitorType

        store = gateway._monitor_store
        sub = ctx.args[0].lower() if ctx.args else "help"
        sub_args = ctx.args[1:] if len(ctx.args) > 1 else []

        if sub == "list":
            monitors = await store.list_monitors(user_id=ctx.event.user_id)
            if not monitors:
                await gateway._send(ctx.event.channel, ctx.event.session_id, "No monitors configured.")
                return True
            lines = ["📊 Your Monitors:"]
            for mon in monitors[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(mon.status.value, "❓")
                last = ""
                if mon.last_check:
                    last = f" {'✅' if mon.last_check.status == 'up' else '❌'}"
                lines.append(f"  {icon} {mon.id[:8]} {mon.name} [{mon.type.value}] every {mon.interval_seconds}s{last}")
            await gateway._send(ctx.event.channel, ctx.event.session_id, "\n".join(lines))

        elif sub in ("add", "remove", "pause", "resume"):
            if not gateway._check_permission(ctx.user, Permission.MONITOR_WRITE):
                await gateway._send(ctx.event.channel, ctx.event.session_id, "Access denied: insufficient permissions")
                return True

        if sub == "add":
            if len(sub_args) < 2:
                await gateway._send(
                    ctx.event.channel,
                    ctx.event.session_id,
                    "Usage: /monitor add <type> <target> [name]\n"
                    "Types: http <url>, price <symbol>, rss <url>, file <path>, process <name>",
                )
                return True
            mtype = sub_args[0].lower()
            target = sub_args[1]
            name = " ".join(sub_args[2:]) if len(sub_args) > 2 else f"{mtype}:{target[:30]}"
            type_map = {
                "http": MonitorType.HTTP,
                "price": MonitorType.PRICE,
                "rss": MonitorType.RSS,
                "file": MonitorType.FILE,
                "process": MonitorType.PROCESS,
            }
            if mtype not in type_map:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Unknown type: {mtype}")
                return True
            monitor = Monitor(
                name=name,
                type=type_map[mtype],
                target=target,
                interval_seconds=300,
                status=MonitorStatus.ACTIVE,
                user_id=ctx.event.user_id,
                channel=ctx.event.channel,
            )
            await store.save_monitor(monitor)
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"✅ Monitor '{name}' ({monitor.id[:8]}) added. Checks every 5min.",
            )

        elif sub == "remove" and sub_args:
            m = await store.load_monitor(sub_args[0])
            if not m:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Monitor not found: {sub_args[0]}")
                return True
            await store.delete_monitor(sub_args[0])
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"🗑 Monitor '{m.name}' removed.")

        elif sub == "pause" and sub_args:
            m = await store.load_monitor(sub_args[0])
            if not m:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Monitor not found: {sub_args[0]}")
                return True
            await store.update_status(sub_args[0], MonitorStatus.PAUSED)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"⏸ Monitor '{m.name}' paused.")

        elif sub == "resume" and sub_args:
            m = await store.load_monitor(sub_args[0])
            if not m:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Monitor not found: {sub_args[0]}")
                return True
            await store.update_status(sub_args[0], MonitorStatus.ACTIVE)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"▶️ Monitor '{m.name}' resumed.")

        else:
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                "📊 Monitor commands:\n"
                "  /monitor list\n"
                "  /monitor add http <url>\n"
                "  /monitor add price <symbol>\n"
                "  /monitor add rss <url>\n"
                "  /monitor add file <path>\n"
                "  /monitor add process <name>\n"
                "  /monitor remove <id>\n"
                "  /monitor pause <id>\n"
                "  /monitor resume <id>",
            )
        return True
