from __future__ import annotations

# mypy: disable-error-code="attr-defined"
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from raven.core.auth import Permission
from raven.core.config import settings

if TYPE_CHECKING:
    from raven.core.models import IncomingMessage


class CommandHandlersMixin:
    """Mixin for Gateway command handler methods.

    Requires the host class to provide: self._send(), self._check_permission(),
    self.db, self.channels.
    """

    def _init_stores(self) -> None:
        from raven.core.monitor.store import MonitorStore
        from raven.core.routine.store import RoutineStore

        self._monitor_store = MonitorStore(self.db.db_path)
        self._routine_store = RoutineStore(self.db.db_path)

    async def _handle_monitor_cmd(self, event: IncomingMessage, user: dict[str, Any], sub: str, args: list[str]) -> None:
        from raven.core.monitor.models import Monitor, MonitorStatus, MonitorType

        store = self._monitor_store

        if sub == "list":
            monitors = store.list_monitors(user_id=event.user_id)
            if not monitors:
                await self._send(event.channel, event.session_id, "No monitors configured.")
                return
            lines = ["📊 Your Monitors:"]
            for mon in monitors[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(mon.status.value, "❓")
                last = ""
                if mon.last_check:
                    last = f" {'✅' if mon.last_check.status == 'up' else '❌'}"
                lines.append(f"  {icon} {mon.id[:8]} {mon.name} [{mon.type.value}] every {mon.interval_seconds}s{last}")
            await self._send(event.channel, event.session_id, "\n".join(lines))

        elif sub in ("add", "remove", "pause", "resume"):
            if not self._check_permission(user, Permission.MONITOR_WRITE):
                await self._send(event.channel, event.session_id, "Access denied: insufficient permissions")
                return

        if sub == "add":
            if len(args) < 2:
                await self._send(
                    event.channel,
                    event.session_id,
                    "Usage: /monitor add <type> <target> [name]\n"
                    "Types: http <url>, price <symbol>, rss <url>, file <path>, process <name>",
                )
                return
            mtype = args[0].lower()
            target = args[1]
            name = " ".join(args[2:]) if len(args) > 2 else f"{mtype}:{target[:30]}"

            type_map = {
                "http": MonitorType.HTTP,
                "price": MonitorType.PRICE,
                "rss": MonitorType.RSS,
                "file": MonitorType.FILE,
                "process": MonitorType.PROCESS,
            }
            if mtype not in type_map:
                await self._send(event.channel, event.session_id, f"Unknown type: {mtype}")
                return

            monitor = Monitor(
                name=name,
                type=type_map[mtype],
                target=target,
                interval_seconds=300,
                status=MonitorStatus.ACTIVE,
                user_id=event.user_id,
                channel=event.channel,
            )
            store.save_monitor(monitor)
            await self._send(
                event.channel, event.session_id, f"✅ Monitor '{name}' ({monitor.id[:8]}) added. Checks every 5min."
            )

        elif sub == "remove" and args:
            m = store.load_monitor(args[0])
            if not m:
                await self._send(event.channel, event.session_id, f"Monitor not found: {args[0]}")
                return
            store.delete_monitor(args[0])
            await self._send(event.channel, event.session_id, f"🗑 Monitor '{m.name}' removed.")

        elif sub == "pause" and args:
            m = store.load_monitor(args[0])
            if not m:
                await self._send(event.channel, event.session_id, f"Monitor not found: {args[0]}")
                return
            store.update_status(args[0], MonitorStatus.PAUSED)
            await self._send(event.channel, event.session_id, f"⏸ Monitor '{m.name}' paused.")

        elif sub == "resume" and args:
            m = store.load_monitor(args[0])
            if not m:
                await self._send(event.channel, event.session_id, f"Monitor not found: {args[0]}")
                return
            store.update_status(args[0], MonitorStatus.ACTIVE)
            await self._send(event.channel, event.session_id, f"▶️ Monitor '{m.name}' resumed.")

        else:
            await self._send(
                event.channel,
                event.session_id,
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

    async def _handle_code_cmd(self, event: IncomingMessage, sub: str, args: list[str]) -> None:
        from raven.core.coder.indexer import CodeIndexer
        from raven.core.coder.models import CodingSession, SessionStatus
        from raven.core.coder.review import CodeReviewer
        from raven.core.coder.session import CodingSessionManager

        mgr = CodingSessionManager(self.db.db_path)

        if sub == "index":
            root = args[0] if args else str(Path.cwd())
            await self._send(event.channel, event.session_id, f"Indexing {root}...")
            indexer = CodeIndexer(root)
            indexer.index(max_files=2000)
            summary = indexer.summary()
            langs = ", ".join(f"{k}:{v}" for k, v in summary.get("languages", {}).items())
            await self._send(event.channel, event.session_id, f"Indexed {summary['files']} files\nLanguages: {langs}")

        elif sub == "search" and args:
            query = " ".join(args)
            root = str(Path.cwd())
            indexer = CodeIndexer(root)
            indexer.index(max_files=2000)
            results = indexer.search(query)
            if not results:
                await self._send(event.channel, event.session_id, f"No results for '{query}'")
                return
            lines = [f"🔍 Results for '{query}':"]
            for f in results[:10]:
                syms = ", ".join(s.name for s in f.symbols[:3])
                lines.append(f"  {f.path} [{f.language}] {syms}")
            await self._send(event.channel, event.session_id, "\n".join(lines))

        elif sub == "review" and args:
            path = " ".join(args)
            p = Path(path).expanduser().resolve()
            ws = settings.resolved_workspace
            if ws and not str(p).startswith(str(ws.resolve())):
                await self._send(event.channel, event.session_id, "File outside workspace — denied")
                return
            if not p.is_file():
                await self._send(event.channel, event.session_id, f"File not found: {p}")
                return
            content = p.read_text(encoding="utf-8", errors="replace")
            reviewer = CodeReviewer()
            comments = await reviewer.review_file(str(p), content)
            if not comments:
                await self._send(event.channel, event.session_id, "✅ No issues found!")
                return
            lines = [f"📋 Review: {p.name}"]
            for c in comments[:15]:
                icon = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵", "praise": "🟢"}
                lines.append(f"  {icon.get(c.severity.value, '⚪')} L{c.line}: {c.message}")
            if len(comments) > 15:
                lines.append(f"  ... and {len(comments) - 15} more")
            await self._send(event.channel, event.session_id, "\n".join(lines))

        elif sub == "start" and args:
            goal = " ".join(args)
            project = str(Path.cwd())
            new_session = CodingSession(user_id=event.user_id, channel=event.channel, goal=goal, project_path=project)
            mgr.create_session(new_session)
            await self._send(
                event.channel,
                event.session_id,
                f"💻 Coding session started: {new_session.id[:8]}\n"
                f"Goal: {goal}\n"
                f"Project: {project}\n"
                f"Use /code status {new_session.id[:8]} to check",
            )

        elif sub == "status" and args:
            session = mgr.get_session(args[0])
            if not session:
                await self._send(event.channel, event.session_id, f"Session not found: {args[0]}")
                return
            await self._send(
                event.channel,
                event.session_id,
                f"💻 Session: {session.id[:8]}\n"
                f"Goal: {session.goal}\n"
                f"Status: {session.status.value}\n"
                f"Files: {len(session.files)}\n"
                f"Messages: {len(session.history)}",
            )

        elif sub == "end" and args:
            session = mgr.get_session(args[0])
            if not session:
                await self._send(event.channel, event.session_id, f"Session not found: {args[0]}")
                return
            session.status = SessionStatus.COMPLETED
            mgr.update_session(session)
            await self._send(event.channel, event.session_id, f"Session {args[0][:8]} ended.")

        else:
            await self._send(
                event.channel,
                event.session_id,
                "💻 Code commands:\n"
                "  /code index [path] - Index a codebase\n"
                "  /code search <query> - Search indexed code\n"
                "  /code review <file> - Review a file\n"
                "  /code start <goal> - Start coding session\n"
                "  /code status <id> - Session status\n"
                "  /code end <id> - End session",
            )

    async def _handle_routine_cmd(self, event: IncomingMessage, user: dict[str, Any], sub: str, args: list[str]) -> None:
        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

        store = self._routine_store

        if sub == "list":
            routines = store.list_routines(user_id=event.user_id)
            if not routines:
                await self._send(event.channel, event.session_id, "No routines configured.")
                return
            lines = ["⏰ Your Routines:"]
            for rt in routines[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(rt.status.value, "❓")
                last = f" last: {rt.last_run_status}" if rt.last_run_status else ""
                lines.append(f"  {icon} {rt.id[:8]} {rt.name} [{rt.action.value}] {rt.schedule}{last}")
            await self._send(event.channel, event.session_id, "\n".join(lines))

        elif sub in ("add", "remove", "pause", "resume"):
            if not self._check_permission(user, Permission.ROUTINE_WRITE):
                await self._send(event.channel, event.session_id, "Access denied: insufficient permissions")
                return

        if sub == "add":
            if len(args) < 2:
                await self._send(
                    event.channel,
                    event.session_id,
                    "Usage: /routine add <action> <schedule> [name]\n"
                    "Actions: send_briefing, send_message, check_email, organize_files\n"
                    "Schedule: HH:MM, cron, or interval_seconds",
                )
                return
            action = args[0].lower()
            schedule = args[1]
            name = " ".join(args[2:]) if len(args) > 2 else f"{action}@{schedule}"

            action_map = {
                "send_briefing": RoutineAction.SEND_BRIEFING,
                "send_message": RoutineAction.SEND_MESSAGE,
                "check_email": RoutineAction.CHECK_EMAIL,
                "organize_files": RoutineAction.ORGANIZE_FILES,
            }
            if action not in action_map:
                await self._send(event.channel, event.session_id, f"Unknown action: {action}")
                return

            if ":" in schedule:
                trigger = RoutineTrigger.SCHEDULED
            else:
                try:
                    int(schedule)
                    trigger = RoutineTrigger.INTERVAL
                except ValueError:
                    trigger = RoutineTrigger.SCHEDULED

            routine = Routine(
                name=name,
                action=action_map[action],
                trigger=trigger,
                schedule=schedule,
                status=RoutineStatus.ACTIVE,
                user_id=event.user_id,
                channel=event.channel,
            )
            store.save_routine(routine)
            await self._send(
                event.channel,
                event.session_id,
                f"⏰ Routine '{name}' ({routine.id[:8]}) added. {trigger.value}: {schedule}",
            )

        elif sub == "remove" and args:
            r = store.load_routine(args[0])
            if not r:
                await self._send(event.channel, event.session_id, f"Routine not found: {args[0]}")
                return
            store.delete_routine(args[0])
            await self._send(event.channel, event.session_id, f"🗑 Routine '{r.name}' removed.")

        elif sub == "pause" and args:
            r = store.load_routine(args[0])
            if not r:
                await self._send(event.channel, event.session_id, f"Routine not found: {args[0]}")
                return
            store.update_status(args[0], RoutineStatus.PAUSED)
            await self._send(event.channel, event.session_id, f"⏸ Routine '{r.name}' paused.")

        elif sub == "resume" and args:
            r = store.load_routine(args[0])
            if not r:
                await self._send(event.channel, event.session_id, f"Routine not found: {args[0]}")
                return
            store.update_status(args[0], RoutineStatus.ACTIVE)
            await self._send(event.channel, event.session_id, f"▶️ Routine '{r.name}' resumed.")

        else:
            await self._send(
                event.channel,
                event.session_id,
                "⏰ Routine commands:\n"
                "  /routine list\n"
                "  /routine add <action> <schedule> [name]\n"
                "  /routine remove <id>\n"
                "  /routine pause <id>\n"
                "  /routine resume <id>",
            )

    async def _handle_voice_cmd(self, event: IncomingMessage, sub: str, args: list[str]) -> None:
        if sub == "tts":
            text = " ".join(args) if args else ""
            if not text:
                await self._send(event.channel, event.session_id, "Usage: /voice tts <text>")
                return
            from raven.voice import TextToSpeech

            tts = TextToSpeech()
            try:
                output = await asyncio.get_event_loop().run_in_executor(None, tts.synthesize, text)
                await self._send(event.channel, event.session_id, f"🔊 TTS saved to: {output}")
            except Exception as e:
                await self._send(event.channel, event.session_id, f"❌ TTS failed: {e}")

        elif sub == "providers":
            from raven.voice import TTSProvider

            providers = [p.value for p in TTSProvider]
            await self._send(
                event.channel, event.session_id, "🔊 TTS Providers:\n" + "\n".join(f"  • {p}" for p in providers)
            )

        else:
            await self._send(
                event.channel,
                event.session_id,
                "🔊 Voice commands:\n  /voice tts <text> - Synthesize speech\n  /voice providers - List TTS providers",
            )
