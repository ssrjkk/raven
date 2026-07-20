from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from raven.core.auth import Permission
from raven.core.config import settings
from raven.core.gateway.commands.base import CommandContext, CommandHandler
from raven.core.security.sandbox_policy import check_tool_allowed, get_policy_for_channel

if TYPE_CHECKING:
    pass


class CodeCommand(CommandHandler):
    name = "code"
    description = "Code management"

    async def execute(self, ctx: CommandContext) -> bool:
        gateway = self.gateway
        policy = get_policy_for_channel(ctx.event.channel)
        if policy is not None:
            allowed, msg = check_tool_allowed(policy, "write", ctx.event.channel)
            if not allowed:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Access denied: {msg}")
                return True
        if not gateway._check_permission(ctx.user, Permission.CODE_READ):
            await gateway._send(ctx.event.channel, ctx.event.session_id, "Access denied: insufficient permissions")
            return True

        from raven.core.coder.indexer import CodeIndexer
        from raven.core.coder.models import CodingSession, SessionStatus
        from raven.core.coder.review import CodeReviewer
        from raven.core.coder.session import CodingSessionManager

        mgr = CodingSessionManager(gateway.db.db_path)
        sub = ctx.args[0].lower() if ctx.args else "help"
        sub_args = ctx.args[1:] if len(ctx.args) > 1 else []

        if sub == "index":
            root = sub_args[0] if sub_args else str(Path.cwd())
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Indexing {root}...")
            indexer = CodeIndexer(root)
            await asyncio.to_thread(indexer.index, max_files=2000)
            summary = indexer.summary()
            langs = ", ".join(f"{k}:{v}" for k, v in summary.get("languages", {}).items())
            await gateway._send(
                ctx.event.channel, ctx.event.session_id, f"Indexed {summary['files']} files\nLanguages: {langs}"
            )

        elif sub == "search" and sub_args:
            query = " ".join(sub_args)
            root = str(Path.cwd())
            indexer = CodeIndexer(root)
            await asyncio.to_thread(indexer.index, max_files=2000)
            results = indexer.search(query)
            if not results:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"No results for '{query}'")
                return True
            lines = [f"🔍 Results for '{query}':"]
            for f in results[:10]:
                syms = ", ".join(s.name for s in f.symbols[:3])
                lines.append(f"  {f.path} [{f.language}] {syms}")
            await gateway._send(ctx.event.channel, ctx.event.session_id, "\n".join(lines))

        elif sub == "review" and sub_args:
            path = " ".join(sub_args)
            p = Path(path).expanduser().resolve()
            ws = settings.resolved_workspace
            if ws and not str(p).startswith(str(ws.resolve())):
                await gateway._send(ctx.event.channel, ctx.event.session_id, "File outside workspace — denied")
                return True
            is_file = await asyncio.to_thread(p.is_file)
            if not is_file:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"File not found: {p}")
                return True
            content = await asyncio.to_thread(lambda: p.read_text(encoding="utf-8", errors="replace"))
            reviewer = CodeReviewer()
            comments = await reviewer.review_file(str(p), content)
            if not comments:
                await gateway._send(ctx.event.channel, ctx.event.session_id, "✅ No issues found!")
                return True
            lines = [f"📋 Review: {p.name}"]
            for c in comments[:15]:
                icon = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵", "praise": "🟢"}
                lines.append(f"  {icon.get(c.severity.value, '⚪')} L{c.line}: {c.message}")
            if len(comments) > 15:
                lines.append(f"  ... and {len(comments) - 15} more")
            await gateway._send(ctx.event.channel, ctx.event.session_id, "\n".join(lines))

        elif sub == "start" and sub_args:
            goal = " ".join(sub_args)
            project = str(Path.cwd())
            new_session = CodingSession(
                user_id=ctx.event.user_id, channel=ctx.event.channel, goal=goal, project_path=project
            )
            await mgr.create_session(new_session)
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"💻 Coding session started: {new_session.id[:8]}\n"
                f"Goal: {goal}\n"
                f"Project: {project}\n"
                f"Use /code status {new_session.id[:8]} to check",
            )

        elif sub == "status" and sub_args:
            session = await mgr.get_session(sub_args[0])
            if not session:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Session not found: {sub_args[0]}")
                return True
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                f"💻 Session: {session.id[:8]}\n"
                f"Goal: {session.goal}\n"
                f"Status: {session.status.value}\n"
                f"Files: {len(session.files)}\n"
                f"Messages: {len(session.history)}",
            )

        elif sub == "end" and sub_args:
            session = await mgr.get_session(sub_args[0])
            if not session:
                await gateway._send(ctx.event.channel, ctx.event.session_id, f"Session not found: {sub_args[0]}")
                return True
            session.status = SessionStatus.COMPLETED
            await mgr.update_session(session)
            await gateway._send(ctx.event.channel, ctx.event.session_id, f"Session {sub_args[0][:8]} ended.")

        else:
            await gateway._send(
                ctx.event.channel,
                ctx.event.session_id,
                "💻 Code commands:\n"
                "  /code index [path] - Index a codebase\n"
                "  /code search <query> - Search indexed code\n"
                "  /code review <file> - Review a file\n"
                "  /code start <goal> - Start coding session\n"
                "  /code status <id> - Session status\n"
                "  /code end <id> - End session",
            )
        return True
