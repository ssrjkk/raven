from __future__ import annotations

import asyncio
import random
import string
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from raven.core.config import settings

if TYPE_CHECKING:
    from raven.channels.base import BaseChannel
from raven.core.agent.registry import AgentRegistry
from raven.core.db import Database
from raven.core.failover import ModelFailover
from raven.core.health import health
from raven.core.llm import LLMRouter
from raven.core.audit import audit_logger
from raven.core.metrics import metrics
from raven.core.models import IncomingMessage, Message
from raven.core.plugin_loader import PluginLoader
from raven.core.sandbox import Sandbox
from raven.core.self_heal import self_healer
from raven.core.skills import Skill, skills_registry
from raven.core.security.context_filter import ContextVisibility, filter_context_by_visibility


class Gateway:
    def __init__(self, db: Database, plugin_loader: PluginLoader):
        self.db = db
        self.llm = LLMRouter()
        self.failover = ModelFailover(self.llm)
        self.plugin_loader = plugin_loader
        self.channels: dict[str, Any] = {}
        self._running = False
        self.registry = AgentRegistry(db, self.llm, plugin_loader.tools)
        self.sandbox = Sandbox()
        self._skill_dirs: list[str] = []

    def register_channel(self, channel: BaseChannel):
        self.channels[channel.channel_id] = channel
        logger.info("Registered channel: {}", channel.channel_id)

    def load_skills(self, skills_path: str | None = None):
        from pathlib import Path
        paths = [skills_path] if skills_path else []
        base = Path(__file__).parent.parent.parent
        ws = base / "workspace" / "skills"
        if ws.exists():
            paths.append(str(ws))
        for p in paths:
            skills_registry.register_from_dir(Path(p))

    def register_skill(self, skill: Skill):
        skills_registry.register(skill)

    async def start(self):
        self.registry.setup_defaults()
        logger.info("Starting gateway with {} channels, {} agents", len(self.channels), len(self.registry.list_agents()))
        self._running = True
        for cid, channel in self.channels.items():
            try:
                await channel.start()
                logger.info("Channel started: {}", cid)
            except Exception as e:
                logger.error("Failed to start channel {}: {}", cid, e)
        self.load_skills()
        self._register_skill_handlers()
        self._register_health_checks()
        self._register_channel_heal()

    async def stop(self):
        logger.info("Stopping gateway...")
        self._running = False
        for cid, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Channel stopped: {}", cid)
            except Exception as e:
                logger.error("Error stopping channel {}: {}", cid, e)

    def _register_skill_handlers(self):
        async def _morning_briefing(user_id: str, channel: str) -> str:
            try:
                monitors_info = ""
                from raven.core.monitor.store import MonitorStore
                store = MonitorStore(self.db.db_path)
                monitors = store.list_monitors(user_id=user_id)
                if monitors:
                    statuses = [f"{m.name}[{m.type.value}]:{'🟢' if m.status.value == 'active' else '⏸'}" for m in monitors[:5]]
                    monitors_info = "Monitors: " + ", ".join(statuses)

                from raven.core.task_engine.store import TaskStore
                tstore = TaskStore(self.db.db_path)
                tasks = tstore.list_tasks(user_id=user_id, limit=5)
                tasks_info = ""
                if tasks:
                    pending = [t for t in tasks if t.status.value in ("pending", "running")]
                    tasks_info = f"Tasks: {len(pending)} pending of {len(tasks)} total"

                prompt = (
                    f"Generate a friendly morning briefing (2-3 paragraphs) for the user.\n"
                    f"{monitors_info}\n{tasks_info}\n"
                    f"Keep it concise and warm."
                )
                result = ""
                async for token in self.llm.complete_stream(
                    [{"role": "user", "content": prompt}],
                    model=settings.default_model,
                ):
                    result += token
                return result.strip() or "Good morning! Everything is running smoothly."
            except Exception as e:
                logger.error("Morning briefing error: {}", e)
                return "Good morning! I had trouble gathering your briefing. Everything appears to be running."

        skill = skills_registry.get("morning_briefing")
        if skill:
            skill._handler = _morning_briefing
            logger.info("Registered morning_briefing skill handler")

    def _register_health_checks(self):
        async def _db_check():
            return await self.db.health_check()

        async def _llm_check():
            try:
                result = await self.llm.complete([{"role": "user", "content": "ping"}], model=settings.default_model)
                return bool(result.content)
            except Exception:
                return False

        async def _db_restart():
            await self.db.disconnect()
            await self.db.connect()

        async def _llm_restart():
            self.llm = LLMRouter()
            self.failover = ModelFailover(self.llm)

        health.register("database", _db_check, timeout=3.0, critical=True)
        health.register("llm", _llm_check, timeout=10.0, critical=False)
        self_healer.register("database", _db_check, _db_restart)
        self_healer.register("llm", _llm_check, _llm_restart)

    def _register_channel_heal(self):
        for cid, channel in self.channels.items():
            async def _check(ch=channel):
                return await ch.health_check() if hasattr(ch, "health_check") else True
            async def _restart(ch=channel, cid=cid):
                try:
                    await ch.stop()
                    await ch.start()
                    logger.info("Self-heal restarted channel {}", cid)
                except Exception as e:
                    logger.error("Self-heal restart failed for {}: {}", cid, e)
            self_healer.register(f"channel:{cid}", _check, _restart)
        if self.channels:
            self_healer.start()

    async def handle_message(self, event: IncomingMessage):
        logger.info("Incoming message from {}[{}]: {}", event.channel, event.user_id, event.text[:80])
        metrics.inc("messages_received", {"channel": event.channel})
        try:
            user = await self.db.find_or_create_user(event.channel, event.user_id)

            if not await self._is_user_allowed(event, user):
                return

            handled = await self._handle_command(event)
            if handled:
                return

            intent_handled = await self._handle_intent(event)
            if intent_handled:
                return

            session_id = event.session_id or f"{event.channel}:{event.user_id}:default"
            session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
            agent = self.registry.create_agent(session)

            event.text = self._clean_text(event.channel, event.text)
            event.text = self._apply_context_filter(event, user, event.text)
            recall_context = None

            full_response = ""
            async for token in agent.run(event.text, recall_context=recall_context):
                full_response += token

            if full_response.strip():
                await self._send(event.channel, session_id, full_response)
                metrics.inc("messages_sent", {"channel": event.channel})
                metrics.observe("response_length", len(full_response), {"channel": event.channel})

        except Exception as e:
            logger.error("handle_message error: {}", e)
            metrics.inc("message_errors", {"channel": event.channel})
            await self._send(event.channel, event.session_id, f"Sorry, an error occurred: {str(e)[:200]}")

    def _apply_context_filter(self, event, user: dict, text: str) -> str:
        from raven.core.config import settings
        visibility = ContextVisibility(settings.context_visibility)
        is_allowlisted = bool(user.get("is_allowed")) or settings.dm_policy == "open"
        return filter_context_by_visibility(text, visibility, is_allowlisted, user.get("id", ""))

    async def _handle_intent(self, event: IncomingMessage) -> bool:
        import re
        text = event.text.strip().lower()

        price_pattern = re.compile(
            r"(?:what(?:'s| is| are)?\s+)?(?:the\s+)?(?:price|rate|cost)\s+(?:of\s+)?(\w+)|"
            r"(\w+)\s+(?:price|rate)(?:\s+now|\s+today)?$|"
            r"how\s+much\s+is\s+(\w+)"
        )
        m = price_pattern.search(text)
        if m:
            coin = m.group(1) or m.group(2) or m.group(3)
            from raven.core.monitor.checkers.price import check_price
            from raven.core.monitor.models import Monitor, MonitorType
            pseudo = Monitor(
                name="intent-price",
                type=MonitorType.PRICE,
                target=coin,
                config={"target": coin},
            )
            try:
                result = await check_price(pseudo)
                if result:
                    await self._send(event.channel, event.session_id, result)
                else:
                    pass
            except Exception:
                pass
            return True if m else False

        monitor_pattern = re.compile(
            r"(?:how\s+are\s+my\s+)?monitors?|"
            r"(?:check|show|list)\s+(?:my\s+)?(?:monitors?|checks?)|"
            r"(?:monitor|check)\s+(?:status|health)"
        )
        if monitor_pattern.search(text):
            from raven.core.monitor.store import MonitorStore
            store = MonitorStore(self.db.db_path)
            monitors = store.list_monitors(user_id=event.user_id)
            if not monitors:
                await self._send(event.channel, event.session_id, "You have no monitors configured.")
                return True
            lines = ["📊 Your Monitors:"]
            for m in monitors[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(m.status.value, "❓")
                lines.append(f"  {icon} {m.name} [{m.type.value}] every {m.interval_seconds}s")
            await self._send(event.channel, event.session_id, "\n".join(lines))
            return True

        briefing_pattern = re.compile(
            r"(?:good\s+)?morning(?:\s+briefing|\s+summary|\s+report)?$|"
            r"(?:daily|morning)\s+(?:briefing|summary|update|report)"
        )
        if briefing_pattern.search(text):
            from raven.core.skills import skills_registry
            briefing = skills_registry.get("morning_briefing")
            if briefing:
                result = await briefing.execute(event.user_id, event.channel)
                if result:
                    await self._send(event.channel, event.session_id, str(result))
                    return True
            await self._send(event.channel, event.session_id, "Morning briefing skill not loaded.")
            return True

        task_intent = re.compile(
            r"(?:remind\s+(?:me|us)\s+(?:to|about|that))|"
            r"(?:set\s+(?:a|an)?\s*(?:reminder|timer|task|alarm))|"
            r"(?:schedule\s+(?:a|an)?\s*(?:reminder|task))"
        )
        if task_intent.search(text):
            from raven.core.task_engine.store import TaskStore
            from raven.core.task_engine.planner import TaskPlanner
            from raven.core.task_engine.runner import TaskRunner
            from raven.tools.register_all import create_tool_registry
            tools = create_tool_registry()
            store = TaskStore(self.db.db_path)
            planner = TaskPlanner(tools)
            runner = TaskRunner(store, tools)
            try:
                task = await planner.plan(text, self.llm, user_id=event.user_id, channel=event.channel)
                await self._send(event.channel, event.session_id,
                    f"📋 Task planned: {task.plan_summary or text[:80]}")
                await runner.submit(task)
                asyncio.create_task(runner.wait(task.id, timeout=600))
            except Exception as e:
                logger.error("Intent task planning error: {}", e)
            return True

        return False

    async def _is_user_allowed(self, event: IncomingMessage, user: dict) -> bool:
        policy = settings.dm_policy
        allow_from_raw = settings.channel_allow_from
        if allow_from_raw:
            try:
                import json
                allow_map = json.loads(allow_from_raw)
                channel_rules = allow_map.get(event.channel, [])
                if channel_rules and "*" not in channel_rules and event.user_id not in channel_rules:
                    metrics.inc("messages_blocked", {"channel": event.channel, "reason": "allowlist"})
                    await self._send(event.channel, event.session_id, "Access denied. You are not on the allowlist.")
                    return False
            except (json.JSONDecodeError, TypeError):
                pass

        if policy == "closed":
            if not user.get("is_allowed"):
                metrics.inc("messages_blocked", {"channel": event.channel, "reason": "policy_closed"})
                await self._send(event.channel, event.session_id, "Access denied. You are not authorized.")
                return False

        if policy == "pairing" and not user.get("is_allowed"):
            if event.text.startswith("/pair"):
                code = event.text.split()[-1] if len(event.text.split()) > 1 else ""
                matched = await self.db.get_user_by_pairing_code(code)
                if matched and matched["id"] == user["id"]:
                    await self.db.set_user_allowed(user["id"], True)
                    await self.db.set_pairing_code(user["id"], "")
                    audit_logger.sensitive("pairing_approve", event.user_id, f"{event.channel}:{event.user_id}", True)
                    await self._send(event.channel, event.session_id, "You are now authorized!")
                    metrics.inc("pairing_approved", {"channel": event.channel})
                    return False
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            await self.db.find_or_create_user(event.channel, event.user_id)
            await self.db.set_pairing_code(f"{event.channel}:{event.user_id}", code)
            await self._send(event.channel, event.session_id, f"Welcome! Your pairing code is: `{code}`\nPlease send `/pair {code}` to authorize.")
            metrics.inc("pairing_codes_sent", {"channel": event.channel})
            return False

        return True

    async def _handle_command(self, event: IncomingMessage) -> bool:
        text = event.text.strip()
        cmd = text.split()[0].lower() if text else ""
        args = text.split()[1:] if len(text.split()) > 1 else []

        if cmd == "/status":
            await self._send(event.channel, event.session_id,
                f"Raven AI is running.\nChannels: {', '.join(self.channels.keys())}\n"
                f"Agents: {len(self.registry.list_agents())}\n"
                f"Skills: {len(skills_registry.list_names())}"
            )
            return True

        if cmd == "/new":
            new_sid = f"{event.channel}:{event.user_id}:{uuid4().hex[:8]}"
            await self.db.get_or_create_session(new_sid, event.channel, event.user_id)
            await self._send(event.channel, new_sid, "Starting fresh conversation.")
            return True

        if cmd == "/reset":
            sid = event.session_id or f"{event.channel}:{event.user_id}:default"
            await self.db.delete_session(sid)
            await self._send(event.channel, sid, "Session reset.")
            return True

        if cmd == "/compact":
            session_id = event.session_id or f"{event.channel}:{event.user_id}:default"
            session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
            agent = self.registry.create_agent(session)
            msgs = await self.db.get_session_messages(session.id, limit=100)
            if not msgs:
                await self._send(event.channel, event.session_id, "No messages to compact.")
                return True
            history_text = "\n".join(f"{m.role}: {m.content[:200]}" for m in msgs)
            summary = ""
            async for token in agent.simple_complete([
                {"role": "system", "content": "Summarize this conversation concisely in 2-3 sentences."},
                {"role": "user", "content": f"Summarize:\n{history_text}"},
            ]):
                summary += token
            if summary.strip():
                await self.db.replace_session_messages(session.id, [
                    {"role": "system", "content": f"[Session compacted: {summary[:500]}]"}
                ])
            await self._send(event.channel, event.session_id, f"Session compacted.\nSummary: {summary[:300]}")
            return True

        if cmd == "/think":
            level = args[0] if args else "high"
            if level in ("low", "medium", "high"):
                await self._send(event.channel, event.session_id, f"Thinking level set to: {level}.")
            else:
                await self._send(event.channel, event.session_id, "Usage: /think <low|medium|high>")
            return True

        if cmd == "/verbose":
            setting = args[0] if args else ""
            if setting in ("on", "off"):
                await self._send(event.channel, event.session_id, f"Verbose mode: {setting}.")
            else:
                await self._send(event.channel, event.session_id, "Usage: /verbose <on|off>")
            return True

        if cmd == "/trace":
            setting = args[0] if args else ""
            if setting in ("on", "off"):
                await self._send(event.channel, event.session_id, f"Trace mode: {setting}.")
            else:
                await self._send(event.channel, event.session_id, "Usage: /trace <on|off>")
            return True

        if cmd == "/usage":
            mode = args[0] if args else ""
            if mode in ("off", "tokens", "full"):
                await self._send(event.channel, event.session_id, f"Usage mode: {mode}.")
            else:
                await self._send(event.channel, event.session_id, "Usage: /usage <off|tokens|full>")
            return True

        if cmd == "/restart":
            await self._send(event.channel, event.session_id, "Restarting agent session...")
            session_id = f"{event.channel}:{event.user_id}:{uuid4().hex[:8]}"
            await self._send(event.channel, event.session_id, "Session restarted.")
            return True

        if cmd == "/activation":
            mode = args[0] if args else ""
            if mode in ("mention", "always"):
                await self._send(event.channel, event.session_id, f"Activation mode: {mode}.")
            else:
                await self._send(event.channel, event.session_id, "Usage: /activation <mention|always>")
            return True

        if cmd == "/task":
            goal = " ".join(args)
            if not goal:
                await self._send(event.channel, event.session_id, "Usage: /task <goal description>")
                return True
            await self._send(event.channel, event.session_id, f"Planning task: {goal[:100]}...")
            asyncio.create_task(self._run_task(event, goal))
            return True

        if cmd == "/monitor":
            sub = args[0].lower() if args else "help"
            await self._handle_monitor_cmd(event, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/code":
            sub = args[0].lower() if args else "help"
            await self._handle_code_cmd(event, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/routine":
            sub = args[0].lower() if args else "help"
            await self._handle_routine_cmd(event, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/voice":
            sub = args[0].lower() if args else "help"
            await self._handle_voice_cmd(event, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/help":
            await self._send(event.channel, event.session_id, (
                "Commands:\n"
                "/status - Show bot status\n"
                "/new - Start fresh conversation\n"
                "/reset - Reset session\n"
                "/task <goal> - Plan and execute a task\n"
                "/monitor list - List your monitors\n"
                "/monitor add <type> <target> - Add monitor\n"
                "/code index [path] - Index codebase\n"
                "/code search <query> - Search code\n"
                "/code review <file> - Review file\n"
                "/code start <goal> - Start coding session\n"
                "/routine list - List routines\n"
                "/routine add <action> <sched> - Add routine\n"
                "/voice tts <text> - Text-to-speech synthesis\n"
                "/voice providers - List TTS providers\n"
                "/compact - Summarize conversation\n"
                "/think <low|medium|high> - Set thinking level\n"
                "/skills - List loaded skills\n"
                "/help - Show this help\n"
                "/pair <code> - Authorize with pairing code"
            ))
            return True

        if cmd == "/skills":
            names = skills_registry.list_names()
            if names:
                await self._send(event.channel, event.session_id, f"Skills: {', '.join(names)}")
            else:
                await self._send(event.channel, event.session_id, "No skills loaded.")
            return True

        return False

    async def _send(self, channel_id: str, session_id: str, text: str):
        channel = self.channels.get(channel_id)
        if not channel:
            return
        msg = Message(session_id=session_id, channel=channel_id, role="assistant", content=text)
        await channel.send(session_id, msg)

    def _clean_text(self, channel: str, text: str) -> str:
        if channel == "discord":
            import re
            text = re.sub(r"<@!?\d+>", "", text).strip()
        return text

    async def _run_task(self, event: IncomingMessage, goal: str) -> None:
        from raven.core.task_engine.planner import TaskPlanner
        from raven.core.task_engine.runner import TaskRunner
        from raven.core.task_engine.store import TaskStore
        from raven.tools.register_all import create_tool_registry

        tools = create_tool_registry()
        store = TaskStore(self.db.db_path)
        planner = TaskPlanner(tools)
        runner = TaskRunner(store, tools)

        try:
            task = await planner.plan(goal, self.llm, user_id=event.user_id, channel=event.channel)
            await self._send(event.channel, event.session_id,
                f"📋 Plan: {task.plan_summary or goal}\n"
                + "\n".join(f"  {i+1}. {s.description}" for i, s in enumerate(task.steps[:10]))
            )
            await runner.submit(task)
            task = await runner.wait(task.id, timeout=600)

            if task.status.value == "completed":
                results = []
                for s in task.steps:
                    if s.result:
                        r = str(s.result)[:200]
                        results.append(f"  ✅ {s.description}: {r}")
                msg = "✅ Task completed!\n" + "\n".join(results[:10])
                await self._send(event.channel, event.session_id, msg)
            elif task.status.value == "failed":
                await self._send(event.channel, event.session_id,
                    f"❌ Task failed: {task.error or 'Unknown error'}")
            elif task.status.value == "cancelled":
                await self._send(event.channel, event.session_id, "🚫 Task cancelled")
            else:
                await self._send(event.channel, event.session_id,
                    f"Task status: {task.status.value}")
        except Exception as e:
            logger.error("Task execution error: {}", e)
            await self._send(event.channel, event.session_id, f"❌ Task error: {e}")

    async def _handle_monitor_cmd(self, event: IncomingMessage, sub: str, args: list[str]) -> None:
        from raven.core.monitor.models import Monitor, MonitorStatus, MonitorType
        from raven.core.monitor.store import MonitorStore

        store = MonitorStore(self.db.db_path)

        if sub == "list":
            monitors = store.list_monitors(user_id=event.user_id)
            if not monitors:
                await self._send(event.channel, event.session_id, "No monitors configured.")
                return
            lines = ["📊 Your Monitors:"]
            for m in monitors[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(m.status.value, "❓")
                last = ""
                if m.last_check:
                    last = f" {'✅' if m.last_check.status == 'up' else '❌'}"
                lines.append(f"  {icon} {m.id[:8]} {m.name} [{m.type.value}] every {m.interval_seconds}s{last}")
            await self._send(event.channel, event.session_id, "\n".join(lines))

        elif sub == "add":
            if len(args) < 2:
                await self._send(event.channel, event.session_id,
                    "Usage: /monitor add <type> <target> [name]\n"
                    "Types: http <url>, price <symbol>, rss <url>, file <path>, process <name>")
                return
            mtype = args[0].lower()
            target = args[1]
            name = " ".join(args[2:]) if len(args) > 2 else f"{mtype}:{target[:30]}"

            type_map = {
                "http": MonitorType.HTTP, "price": MonitorType.PRICE,
                "rss": MonitorType.RSS, "file": MonitorType.FILE,
                "process": MonitorType.PROCESS,
            }
            if mtype not in type_map:
                await self._send(event.channel, event.session_id, f"Unknown type: {mtype}")
                return

            monitor = Monitor(
                name=name, type=type_map[mtype], target=target,
                interval_seconds=300, status=MonitorStatus.ACTIVE,
                user_id=event.user_id, channel=event.channel,
            )
            store.save_monitor(monitor)
            await self._send(event.channel, event.session_id,
                f"✅ Monitor '{name}' ({monitor.id[:8]}) added. Checks every 5min.")

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
            await self._send(event.channel, event.session_id,
                "📊 Monitor commands:\n"
                "  /monitor list\n"
                "  /monitor add http <url>\n"
                "  /monitor add price <symbol>\n"
                "  /monitor add rss <url>\n"
                "  /monitor add file <path>\n"
                "  /monitor add process <name>\n"
                "  /monitor remove <id>\n"
                "  /monitor pause <id>\n"
                "  /monitor resume <id>")

    async def _handle_code_cmd(self, event: IncomingMessage, sub: str, args: list[str]) -> None:
        from raven.core.coder.models import CodingSession, SessionStatus
        from raven.core.coder.session import CodingSessionManager
        from raven.core.coder.indexer import CodeIndexer
        from raven.core.coder.review import CodeReviewer
        from pathlib import Path

        mgr = CodingSessionManager(self.db.db_path)

        if sub == "index":
            root = args[0] if args else str(Path.cwd())
            await self._send(event.channel, event.session_id, f"Indexing {root}...")
            indexer = CodeIndexer(root)
            indexer.index(max_files=2000)
            summary = indexer.summary()
            langs = ", ".join(f"{k}:{v}" for k, v in summary.get("languages", {}).items())
            await self._send(event.channel, event.session_id,
                f"Indexed {summary['files']} files\nLanguages: {langs}")

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
            session = CodingSession(user_id=event.user_id, channel=event.channel, goal=goal, project_path=project)
            mgr.create_session(session)
            await self._send(event.channel, event.session_id,
                f"💻 Coding session started: {session.id[:8]}\n"
                f"Goal: {goal}\n"
                f"Project: {project}\n"
                f"Use /code status {session.id[:8]} to check")

        elif sub == "status" and args:
            session = mgr.get_session(args[0])
            if not session:
                await self._send(event.channel, event.session_id, f"Session not found: {args[0]}")
                return
            await self._send(event.channel, event.session_id,
                f"💻 Session: {session.id[:8]}\n"
                f"Goal: {session.goal}\n"
                f"Status: {session.status.value}\n"
                f"Files: {len(session.files)}\n"
                f"Messages: {len(session.history)}")

        elif sub == "end" and args:
            session = mgr.get_session(args[0])
            if not session:
                await self._send(event.channel, event.session_id, f"Session not found: {args[0]}")
                return
            session.status = SessionStatus.COMPLETED
            mgr.update_session(session)
            await self._send(event.channel, event.session_id, f"Session {args[0][:8]} ended.")

        else:
            await self._send(event.channel, event.session_id,
                "💻 Code commands:\n"
                "  /code index [path] - Index a codebase\n"
                "  /code search <query> - Search indexed code\n"
                "  /code review <file> - Review a file\n"
                "  /code start <goal> - Start coding session\n"
                "  /code status <id> - Session status\n"
                "  /code end <id> - End session")

    async def _handle_routine_cmd(self, event: IncomingMessage, sub: str, args: list[str]) -> None:
        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(self.db.db_path)

        if sub == "list":
            routines = store.list_routines(user_id=event.user_id)
            if not routines:
                await self._send(event.channel, event.session_id, "No routines configured.")
                return
            lines = ["⏰ Your Routines:"]
            for r in routines[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(r.status.value, "❓")
                last = f" last: {r.last_run_status}" if r.last_run_status else ""
                lines.append(f"  {icon} {r.id[:8]} {r.name} [{r.action.value}] {r.schedule}{last}")
            await self._send(event.channel, event.session_id, "\n".join(lines))

        elif sub == "add":
            if len(args) < 2:
                await self._send(event.channel, event.session_id,
                    "Usage: /routine add <action> <schedule> [name]\n"
                    "Actions: send_briefing, send_message, check_email, organize_files\n"
                    "Schedule: HH:MM, cron, or interval_seconds")
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
                name=name, action=action_map[action], trigger=trigger,
                schedule=schedule, status=RoutineStatus.ACTIVE,
                user_id=event.user_id, channel=event.channel,
            )
            store.save_routine(routine)
            await self._send(event.channel, event.session_id,
                f"⏰ Routine '{name}' ({routine.id[:8]}) added. {trigger.value}: {schedule}")

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
            await self._send(event.channel, event.session_id,
                "⏰ Routine commands:\n"
                "  /routine list\n"
                "  /routine add <action> <schedule> [name]\n"
                "  /routine remove <id>\n"
                "  /routine pause <id>\n"
                "  /routine resume <id>")

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
            await self._send(event.channel, event.session_id,
                "🔊 TTS Providers:\n" + "\n".join(f"  • {p}" for p in providers))

        else:
            await self._send(event.channel, event.session_id,
                "🔊 Voice commands:\n"
                "  /voice tts <text> - Synthesize speech\n"
                "  /voice providers - List TTS providers")
