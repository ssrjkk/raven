from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.auth import Permission
from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.security.sandbox_policy import check_tool_allowed, get_policy_for_channel

if TYPE_CHECKING:
    pass


class RoutineCommand(CommandHandler):
    name = "routine"
    description = "Routine management"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        policy = get_policy_for_channel(ctx.event.channel)
        if policy is not None:
            allowed, msg = check_tool_allowed(policy, "write", ctx.event.channel)
            if not allowed:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Access denied: {msg}")
                return True
        if not gateway._check_permission(ctx.user, Permission.ROUTINE_READ):
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Access denied: insufficient permissions")
            return True

        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

        store = gateway._routine_store
        sub = ctx.args[0].lower() if ctx.args else "help"
        sub_args = ctx.args[1:] if len(ctx.args) > 1 else []

        if sub == "list":
            routines = await store.list_routines(user_id=ctx.event.user_id)
            if not routines:
                await gateway._send(ctx.event.channel, ctx.event.session_id, "No routines configured.")
                return True
            lines = ["⏰ Your Routines:"]
            for rt in routines[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(rt.status.value, "❓")
                last = f" last: {rt.last_run_status}" if rt.last_run_status else ""
                lines.append(f"  {icon} {rt.id[:8]} {rt.name} [{rt.action.value}] {rt.schedule}{last}")
            await gateway._send(ctx.event.channel, ctx.event.session_id, "\n".join(lines))

        elif sub in ("add", "remove", "pause", "resume"):
            if not gateway._check_permission(ctx.user, Permission.ROUTINE_WRITE):
                await gateway._send(ctx.event.channel, ctx.event.session_id, "Access denied: insufficient permissions")
                return True

        if sub == "add":
            if len(sub_args) < 2:
                await gateway._send(
                    ctx.event.channel,
                    ctx.event.session_id,
                    "Usage: /routine add <action> <schedule> [name]\n"
                    "Actions: send_briefing, send_message, check_email, organize_files\n"
                    "Schedule: HH:MM, cron, or interval_seconds",
                )
                return True
            action = sub_args[0].lower()
            raw_schedule = sub_args[1:]

            def _cron_field(tok: str) -> bool:
                t = tok.strip("'\"")
                return t == "*" or t.isdigit() or any(c in t for c in "*/,-")

            if len(raw_schedule) >= 5 and all(_cron_field(t) for t in raw_schedule[:5]):
                schedule = " ".join(t.strip("'\"") for t in raw_schedule[:5])
                name = " ".join(raw_schedule[5:]) if len(raw_schedule) > 5 else f"{action}@{schedule}"
            else:
                schedule = raw_schedule[0]
                name = " ".join(raw_schedule[1:]) if len(raw_schedule) > 1 else f"{action}@{schedule}"
            action_map = {
                "send_briefing": RoutineAction.SEND_BRIEFING,
                "send_message": RoutineAction.SEND_MESSAGE,
                "check_email": RoutineAction.CHECK_EMAIL,
                "organize_files": RoutineAction.ORGANIZE_FILES,
            }
            if action not in action_map:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Unknown action: {action}")
                return True
            if ":" in schedule:
                trigger = RoutineTrigger.SCHEDULED
            else:
                try:
                    int(schedule)
                    trigger = RoutineTrigger.INTERVAL
                except ValueError:
                    trigger = RoutineTrigger.SCHEDULED

            from raven.core.routine.engine import RoutineEngine

            validation_error = RoutineEngine.validate_schedule(schedule)
            if validation_error:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"❌ {validation_error}")
                return True
            routine = Routine(
                name=name,
                action=action_map[action],
                trigger=trigger,
                schedule=schedule,
                status=RoutineStatus.ACTIVE,
                user_id=ctx.event.user_id,
                channel=ctx.event.channel,
            )
            await store.save_routine(routine)
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"⏰ Routine '{name}' ({routine.id[:8]}) added. {trigger.value}: {schedule}",
            )

        elif sub == "remove" and sub_args:
            r = await store.load_routine(sub_args[0])
            if not r:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Routine not found: {sub_args[0]}")
                return True
            await store.delete_routine(sub_args[0])
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"🗑 Routine '{r.name}' removed.")

        elif sub == "pause" and sub_args:
            r = await store.load_routine(sub_args[0])
            if not r:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Routine not found: {sub_args[0]}")
                return True
            await store.update_status(sub_args[0], RoutineStatus.PAUSED)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"⏸ Routine '{r.name}' paused.")

        elif sub == "resume" and sub_args:
            r = await store.load_routine(sub_args[0])
            if not r:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Routine not found: {sub_args[0]}")
                return True
            await store.update_status(sub_args[0], RoutineStatus.ACTIVE)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"▶️ Routine '{r.name}' resumed.")

        else:
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                "⏰ Routine commands:\n"
                "  /routine list\n"
                "  /routine add <action> <schedule> [name]\n"
                "  /routine remove <id>\n"
                "  /routine pause <id>\n"
                "  /routine resume <id>",
            )
        return True
