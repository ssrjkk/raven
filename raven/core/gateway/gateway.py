from __future__ import annotations

import asyncio
import json
import re
import secrets
import string
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from raven.core.agent.registry import AgentRegistry
from raven.core.auth import RBAC, Permission
from raven.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from raven.core.config import settings
from raven.core.context_window import ContextWindowConfig, ContextWindowManager
from raven.core.gateway.channel_manager import ChannelManager
from raven.core.gateway.command_handlers import CommandHandlersMixin
from raven.core.gateway.mcp_bridge import MCPBridge
from raven.core.gateway.task_orchestrator import TaskOrchestrator

if TYPE_CHECKING:
    from raven.channels.base import BaseChannel
from raven.core.audit import audit_logger
from raven.core.channel_guardian import ChannelGuardian
from raven.core.failover import ModelFailover
from raven.core.health import health
from raven.core.llm import LLMRouter
from raven.core.metrics import metrics
from raven.core.models import IncomingMessage, Message
from raven.core.monitor.checkers.price import check_price
from raven.core.monitor.models import Monitor, MonitorType
from raven.core.plugin_loader import PluginLoader
from raven.core.sandbox import Sandbox
from raven.core.security.context_filter import ContextVisibility, filter_context_by_visibility
from raven.core.security.rate_limiter import RateLimiter
from raven.core.security.sandbox_policy import (
    MAIN_SESSION_POLICY,
    check_tool_allowed,
    get_policy_for_channel,
)
from raven.core.self_heal import self_healer
from raven.core.skills import Skill, skills_registry
from raven.core.task_engine.store import TaskStore


class Gateway(CommandHandlersMixin):
    def __init__(self, db: Any, plugin_loader: PluginLoader):
        self.db = db
        self.llm = LLMRouter()
        self.failover = ModelFailover(self.llm)
        self.plugin_loader = plugin_loader
        self.channels = ChannelManager()
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._running = False
        self.registry = AgentRegistry(db, self.llm, plugin_loader.tools)
        self.sandbox = Sandbox()
        self._skill_dirs: list[str] = []
        self._monitor_engine: Any = None
        self._rbac = RBAC()
        self._message_cb = CircuitBreaker("gateway.handle_message", failure_threshold=5, recovery_timeout=30.0)
        self._guardian = ChannelGuardian(on_channel_dead=self._on_channel_dead)
        self.mcp = MCPBridge(send_fn=self._send)

        self._ctxmgr: ContextWindowManager | None = None
        if settings.context_window_enabled and settings.context_window_max_tokens > 0:
            ctx_cfg = ContextWindowConfig(
                max_tokens=settings.context_window_max_tokens,
                warning_threshold=settings.context_window_warning_threshold,
                summarization_threshold=settings.context_window_summarization_threshold,
                hard_limit_threshold=settings.context_window_hard_limit,
                reserved_tokens=settings.context_window_reserved_tokens,
                sliding_window_size=settings.context_window_sliding_size,
            )
            self._ctxmgr = ContextWindowManager(self.llm, ctx_cfg)
        self.tasks = TaskOrchestrator(
            db=self.db,
            llm=self.llm,
            mcp_pool=self.mcp.pool,
            send_notification=self._send,
        )
        self._rate_limiter = RateLimiter()
        self._init_stores()

    def register_channel(self, channel: BaseChannel):
        self.channels.register(channel)
        self._guardian.register(channel)

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
        channel_count = len(self.channels.list_ids())
        logger.info(
            "Starting gateway with {} channels, {} agents", channel_count, len(self.registry.list_agents())
        )
        self._running = True
        await self.tasks.start()
        await self.channels.start_all()
        self.load_skills()
        self._register_skill_handlers()
        self._register_health_checks()
        await self.mcp.start(plugin_loader=self.plugin_loader)
        await self._guardian.start()

    async def stop(self):
        logger.info("Stopping gateway...")
        self._running = False
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()
        await self._guardian.stop()
        await self.tasks.stop()
        await self.mcp.stop()
        await self.channels.stop_all()

    def _register_skill_handlers(self):
        async def _morning_briefing(user_id: str, channel: str) -> str:
            try:
                monitors_info = ""
                monitors = await self._monitor_store.list_monitors(user_id=user_id)
                if monitors:
                    statuses = [
                        f"{m.name}[{m.type.value}]:{'🟢' if m.status.value == 'active' else '⏸'}" for m in monitors[:5]
                    ]
                    monitors_info = "Monitors: " + ", ".join(statuses)

                tstore = TaskStore(self.db.db_path)
                tasks = await tstore.list_tasks(user_id=user_id, limit=5)
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
            except Exception as e:
                logger.warning("LLM health check failed: {}", e)
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

    async def handle_message(self, event: IncomingMessage):
        cid = str(uuid4())[:8]
        logger.info("[{}] Incoming message from {}[{}]: {}", cid, event.channel, event.user_id, event.text[:80])
        metrics.inc("messages_received", {"channel": event.channel})

        if not await self._rate_limiter.check_rate_limit(event.channel, event.user_id, channel_type=event.channel):
            metrics.inc("messages_rate_limited", {"channel": event.channel, "reason": "rate_limiter"})
            await self._send(event.channel, event.session_id, "Please slow down.")
            return

        if not await self._guardian.check_rate_limit(event.channel, event.user_id):
            metrics.inc("messages_rate_limited", {"channel": event.channel, "reason": "guardian"})
            await self._send(event.channel, event.session_id, "Please slow down.")
            return

        try:
            await self._message_cb.call(self._handle_message_inner, event, cid)
        except CircuitBreakerOpenError:
            logger.warning("[{}] Message rejected, circuit breaker open", cid)
            metrics.inc("message_errors", {"channel": event.channel, "reason": "circuit_breaker"})
            await self._send(event.channel, event.session_id, f"Service temporarily unavailable (ref: {cid}).")
        except Exception as e:
            logger.error("[{}] handle_message error: {}", cid, e)
            metrics.inc("message_errors", {"channel": event.channel})
            await self._send(event.channel, event.session_id, f"Sorry, an error occurred (ref: {cid}).")

    async def _manage_context(self, session_id: str) -> None:
        if self._ctxmgr is None:
            return

        msgs = await self.db.get_session_messages(session_id, limit=200)
        if not msgs:
            return

        msg_dicts = [{"role": m.role, "content": m.content} for m in msgs]
        total = await self._ctxmgr.estimate_tokens(msg_dicts)
        ratio = total / self._ctxmgr._config.max_tokens if self._ctxmgr._config.max_tokens > 0 else 0

        metrics.observe("context_window_pct", ratio * 100, {"session_id": session_id})

        if ratio < self._ctxmgr._config.warning_threshold:
            return

        logger.info("Context at {:.1f}% for session {} ({} / {} tokens)", ratio * 100, session_id, total, self._ctxmgr._config.max_tokens)
        metrics.inc("context_window_urgent", {"session_id": session_id})

        managed = await self._ctxmgr.manage(msg_dicts)
        if managed is not msg_dicts:
            await self.db.replace_session_messages(session_id, managed)
            metrics.inc("context_window_managed", {"session_id": session_id})
            logger.info("Context window management applied for session {} ({:.1f}%)", session_id, ratio * 100)

    def _bg_task(self, coro: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def _handle_message_inner(self, event: IncomingMessage, cid: str = ""):
        logger.info("[{}] Processing message from {}[{}]", cid, event.channel, event.user_id)
        user = await self.db.find_or_create_user(event.channel, event.user_id)

        if not await self._is_user_allowed(event, user):
            return

        if not await self._enforce_sandbox_policy(event, user):
            return

        handled = await self._handle_command(event, user)
        if handled:
            return

        intent_handled = await self._handle_intent(event)
        if intent_handled:
            return

        session_id = event.session_id or f"{event.channel}:{event.user_id}:default"
        session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
        session.sandbox_policy = get_policy_for_channel(event.channel)

        await self._manage_context(session_id)

        agent = self.registry.create_agent(session)

        channel_obj = self.channels.get(event.channel)
        supports_stream = hasattr(channel_obj, "send_stream") if channel_obj else False

        full_response = ""
        buffer = ""
        gen = agent.run(event.text)
        timed_out = False
        while True:
            try:
                token = await asyncio.wait_for(gen.__anext__(), timeout=settings.agent_token_timeout)
            except StopAsyncIteration:
                break
            except TimeoutError:
                timed_out = True
                break
            full_response += token
            if supports_stream:
                buffer += token
                if len(buffer) >= 50 or token.endswith(("\n", ".", "!", "?")):
                    await self._send(event.channel, session_id, buffer, streaming=True)
                    buffer = ""

        if timed_out:
            tail = "\n\n[⏱ Response timed out. Try rephrasing or splitting your request.]"
            full_response += tail
            if supports_stream:
                await self._send(event.channel, session_id, tail, streaming=True)

        if supports_stream and buffer:
            await self._send(event.channel, session_id, buffer, streaming=True)

        if full_response.strip():
            if not supports_stream:
                await self._send(event.channel, session_id, full_response, streaming=False)
            metrics.inc("messages_sent", {"channel": event.channel})
            metrics.observe("response_length", len(full_response), {"channel": event.channel})

    def _apply_context_filter(self, event, user: dict[str, Any], text: str) -> str:
        visibility = ContextVisibility(settings.context_visibility)
        is_allowlisted = bool(user.get("is_allowed")) or settings.dm_policy == "open"
        return filter_context_by_visibility(text, visibility, is_allowlisted, user.get("id", ""))

    async def _enforce_sandbox_policy(self, event: IncomingMessage, user: dict[str, object]) -> bool:
        policy = get_policy_for_channel(event.channel)
        if policy is MAIN_SESSION_POLICY:
            return True
        if policy.allowed_tools is not None and len(policy.allowed_tools) == 0:
            logger.warning("[sandbox] Channel {} has empty allowed_tools — all actions blocked", event.channel)
            await self._send(event.channel, event.session_id, "Access denied: channel policy blocks all actions.")
            return False
        logger.debug("[sandbox] Policy '{}' enforced for channel {}", policy.name, event.channel)
        return True

    _PRICE_PATTERN = re.compile(
        r"(?:what(?:'s| is| are)?\s+)?(?:the\s+)?(?:price|rate|cost)\s+(?:of\s+)?(\w+)|"
        r"(\w+)\s+(?:price|rate)(?:\s+now|\s+today)?$|"
        r"how\s+much\s+is\s+(\w+)"
    )
    _MONITOR_PATTERN = re.compile(
        r"(?:how\s+are\s+my\s+)?monitors?|"
        r"(?:check|show|list)\s+(?:my\s+)?(?:monitors?|checks?)|"
        r"(?:monitor|check)\s+(?:status|health)"
    )
    _BRIEFING_PATTERN = re.compile(
        r"(?:good\s+)?morning(?:\s+briefing|\s+summary|\s+report)?$|"
        r"(?:daily|morning)\s+(?:briefing|summary|update|report)"
    )
    _TASK_INTENT = re.compile(
        r"(?:remind\s+(?:me|us)\s+(?:to|about|that))|"
        r"(?:set\s+(?:a|an)?\s*(?:reminder|timer|task|alarm))|"
        r"(?:schedule\s+(?:a|an)?\s*(?:reminder|task))"
    )

    async def _handle_intent(self, event: IncomingMessage) -> bool:
        text = event.text.strip().lower()

        m = self._PRICE_PATTERN.search(text)
        if m:
            coin = m.group(1) or m.group(2) or m.group(3)
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
            except Exception as e:
                logger.warning("Price intent failed: {}", e)
            return True

        if self._MONITOR_PATTERN.search(text):
            monitors = await self._monitor_store.list_monitors(user_id=event.user_id)
            if not monitors:
                await self._send(event.channel, event.session_id, "You have no monitors configured.")
                return True
            lines = ["📊 Your Monitors:"]
            for mon in monitors[:10]:
                icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(mon.status.value, "❓")
                lines.append(f"  {icon} {mon.name} [{mon.type.value}] every {mon.interval_seconds}s")
            await self._send(event.channel, event.session_id, "\n".join(lines))
            return True

        if self._BRIEFING_PATTERN.search(text):
            briefing = skills_registry.get("morning_briefing")
            if briefing:
                result = await briefing.execute(event.user_id, event.channel)
                if result:
                    await self._send(event.channel, event.session_id, str(result))
                    return True
            await self._send(event.channel, event.session_id, "Morning briefing skill not loaded.")
            return True

        if self._TASK_INTENT.search(text):
            try:
                await self.tasks.create_and_run(
                    goal=text,
                    user_id=event.user_id,
                    channel=event.channel,
                    session_id=event.session_id or "",
                )
            except Exception as e:
                logger.error("Intent task planning error: {}", e)
            return True

        return False

    async def _is_user_allowed(self, event: IncomingMessage, user: dict[str, Any]) -> bool:
        policy = settings.dm_policy
        allow_from_raw = settings.channel_allow_from
        if allow_from_raw:
            try:
                allow_map = json.loads(allow_from_raw)
                channel_rules = allow_map.get(event.channel, [])
                if channel_rules and "*" not in channel_rules and event.user_id not in channel_rules:
                    metrics.inc("messages_blocked", {"channel": event.channel, "reason": "allowlist"})
                    await self._send(event.channel, event.session_id, "Access denied. You are not on the allowlist.")
                    return False
            except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                logger.warning("Failed to parse channel_allow_from config: {}", exc)

        if policy == "closed" and not user.get("is_allowed"):
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
                    await audit_logger.sensitive("pairing_approve", event.user_id, f"{event.channel}:{event.user_id}", True)
                    await self._send(event.channel, event.session_id, "You are now authorized!")
                    metrics.inc("pairing_approved", {"channel": event.channel})
                    return False
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            await self.db.find_or_create_user(event.channel, event.user_id)
            await self.db.set_pairing_code(f"{event.channel}:{event.user_id}", code)
            await self._send(
                event.channel,
                event.session_id,
                f"Welcome! Your pairing code is: `{code}`\nPlease send `/pair {code}` to authorize.",
            )
            metrics.inc("pairing_codes_sent", {"channel": event.channel})
            return False

        return True

    async def _handle_command(self, event: IncomingMessage, user: dict[str, Any]) -> bool:
        text = event.text.strip()
        cmd = text.split()[0].lower() if text else ""
        args = text.split()[1:] if len(text.split()) > 1 else []

        if cmd == "/status":
            await self._send(
                event.channel,
                event.session_id,
                f"Raven AI is running.\nChannels: {', '.join(self.channels.list_ids())}\n"
                f"Agents: {len(self.registry.list_agents())}\n"
                f"Skills: {len(skills_registry.list_names())}",
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
            policy = get_policy_for_channel(event.channel)
            if policy is not MAIN_SESSION_POLICY:
                allowed, msg = check_tool_allowed(policy, "read", event.channel)
                if not allowed:
                    await self._send(event.channel, event.session_id, f"Access denied: {msg}")
                    return True
            session_id = event.session_id or f"{event.channel}:{event.user_id}:default"
            session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
            agent = self.registry.create_agent(session)
            msgs = await self.db.get_session_messages(session.id, limit=100)
            if not msgs:
                await self._send(event.channel, event.session_id, "No messages to compact.")
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
                await self.db.replace_session_messages(
                    session.id, [{"role": "system", "content": f"[Session compacted: {summary[:500]}]"}]
                )
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
            new_session_id = f"{event.channel}:{event.user_id}:{uuid4().hex[:8]}"
            await self.db.get_or_create_session(new_session_id, event.channel, event.user_id)
            await self._send(event.channel, new_session_id, "Session restarted.")
            return True

        if cmd == "/activation":
            mode = args[0] if args else ""
            if mode in ("mention", "always"):
                await self._send(event.channel, event.session_id, f"Activation mode: {mode}.")
            else:
                await self._send(event.channel, event.session_id, "Usage: /activation <mention|always>")
            return True

        if cmd == "/task":
            policy = get_policy_for_channel(event.channel)
            if policy is not MAIN_SESSION_POLICY:
                allowed, msg = check_tool_allowed(policy, "gateway", event.channel)
                if not allowed:
                    await self._send(event.channel, event.session_id, f"Access denied: {msg}")
                    return True
            if not self._check_permission(user, Permission.TASK_RUN):
                await self._send(event.channel, event.session_id, "Access denied: insufficient permissions")
                return True
            goal = " ".join(args)
            if not goal:
                await self._send(event.channel, event.session_id, "Usage: /task <goal description>")
                return True
            await self._send(event.channel, event.session_id, f"Planning task: {goal[:100]}...")
            self._bg_task(self.tasks.create_and_run(
                goal=goal,
                user_id=event.user_id,
                channel=event.channel,
                session_id=event.session_id or "",
            ))
            return True

        if cmd == "/mcp":
            servers = self.mcp.connected_count
            if servers == 0:
                await self._send(event.channel, event.session_id, "No MCP servers connected.")
                return True
            lines = [f"🌐 MCP servers ({servers} connected):"]
            for info in self.mcp.list_servers_info():
                lines.append(f"  {info['name']}: {info['tools']} tools")
            await self._send(event.channel, event.session_id, "\n".join(lines))
            return True

        if cmd == "/monitor":
            policy = get_policy_for_channel(event.channel)
            if policy is not MAIN_SESSION_POLICY:
                allowed, msg = check_tool_allowed(policy, "read", event.channel)
                if not allowed:
                    await self._send(event.channel, event.session_id, f"Access denied: {msg}")
                    return True
            if not self._check_permission(user, Permission.MONITOR_READ):
                await self._send(event.channel, event.session_id, "Access denied: insufficient permissions")
                return True
            sub = args[0].lower() if args else "help"
            await self._handle_monitor_cmd(event, user, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/code":
            policy = get_policy_for_channel(event.channel)
            if policy is not MAIN_SESSION_POLICY:
                allowed, msg = check_tool_allowed(policy, "write", event.channel)
                if not allowed:
                    await self._send(event.channel, event.session_id, f"Access denied: {msg}")
                    return True
            if not self._check_permission(user, Permission.CODE_READ):
                await self._send(event.channel, event.session_id, "Access denied: insufficient permissions")
                return True
            sub = args[0].lower() if args else "help"
            await self._handle_code_cmd(event, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/routine":
            policy = get_policy_for_channel(event.channel)
            if policy is not MAIN_SESSION_POLICY:
                allowed, msg = check_tool_allowed(policy, "gateway", event.channel)
                if not allowed:
                    await self._send(event.channel, event.session_id, f"Access denied: {msg}")
                    return True
            if not self._check_permission(user, Permission.ROUTINE_READ):
                await self._send(event.channel, event.session_id, "Access denied: insufficient permissions")
                return True
            sub = args[0].lower() if args else "help"
            await self._handle_routine_cmd(event, user, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/voice":
            sub = args[0].lower() if args else "help"
            await self._handle_voice_cmd(event, sub, args[1:] if len(args) > 1 else [])
            return True

        if cmd == "/help":
            await self._send(
                event.channel,
                event.session_id,
                (
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
                    "/mcp - List connected MCP servers\n"
                    "/skills - List loaded skills\n"
                    "/help - Show this help\n"
                    "/pair <code> - Authorize with pairing code"
                ),
            )
            return True

        if cmd == "/skills":
            names = skills_registry.list_names()
            if names:
                await self._send(event.channel, event.session_id, f"Skills: {', '.join(names)}")
            else:
                await self._send(event.channel, event.session_id, "No skills loaded.")
            return True

        return False

    async def _on_channel_dead(self, channel_id: str) -> None:
        channel = self.channels.remove(channel_id)
        if channel:
            logger.error("Channel {} removed from gateway (dead)", channel_id)
            metrics.inc("channels_dead", {"channel": channel_id})
            try:
                await channel.stop()
            except Exception as e:
                logger.error("Error stopping dead channel {}: {}", channel_id, e)
        remaining = self.channels.list_ids()
        if remaining:
            alert = f"[Alert] Channel '{channel_id}' is dead and has been removed. Remaining: {', '.join(remaining)}"
            logger.warning(alert)
            for cid in remaining:
                try:
                    await self._send(cid, f"alert:{cid}", alert)
                except Exception as e:
                    logger.debug("Failed to send dead-channel alert to {}: {}", cid, e)

    def _check_permission(self, user: dict[str, Any], permission: Permission) -> bool:
        role = user.get("role", "user")
        return self._rbac.has_permission(role, permission)

    async def _send(self, channel_id: str, session_id: str, text: str, streaming: bool = False):
        channel = self.channels.get(channel_id)
        if channel is None:
            logger.warning("Channel '{}' not found for _send, session={}", channel_id, session_id)
            return
        if streaming:
            send_stream = getattr(channel, "send_stream", None)
            if send_stream:
                try:
                    await send_stream(session_id, text)
                    await self._guardian.record_success(channel_id)
                except Exception as e:
                    logger.error("Send stream failed for channel {}: {}", channel_id, e)
                    metrics.inc("send_errors", {"channel": channel_id})
                    await self._guardian.record_error(channel_id)
                return
        msg = Message(session_id=session_id, channel=channel_id, role="assistant", content=text)
        try:
            await channel.send(session_id, msg)
            await self._guardian.record_success(channel_id)
        except Exception as e:
            logger.error("Send failed for channel {}: {}", channel_id, e)
            metrics.inc("send_errors", {"channel": channel_id})
            await self._guardian.record_error(channel_id)

    def _clean_text(self, channel: str, text: str) -> str:
        if channel == "discord":
            text = re.sub(r"<@!?\d+>", "", text).strip()
        return text


