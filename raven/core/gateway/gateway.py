from __future__ import annotations

import asyncio
import json
import re
import secrets
import string
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from loguru import logger

from raven.core.agent.registry import AgentRegistry
from raven.core.agents.orchestrator import AgentOrchestrator
from raven.core.auth import RBAC, Permission
from raven.core.cache.llm_cache import LLMCache
from raven.core.cache.rate_limiter import InMemoryRateLimiter, RedisRateLimiter
from raven.core.cache.redis_client import RedisClient
from raven.core.cache.session_store import SessionStore
from raven.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from raven.core.config import settings
from raven.core.context_window import ContextWindowConfig, ContextWindowManager
from raven.core.events import EventBus
from raven.core.features import FeatureFlags
from raven.core.gateway.channel_manager import ChannelManager
from raven.core.gateway.commands.base import CommandContext
from raven.core.gateway.commands.registry import CommandRegistry
from raven.core.gateway.health_monitor import HealthMonitor
from raven.core.gateway.mcp_bridge import MCPBridge
from raven.core.gateway.message_processor import MessageProcessor
from raven.core.gateway.task_orchestrator import TaskOrchestrator
from raven.core.services import Chunker, EntityExtractor
from raven.core.services.persister import get_persister

if TYPE_CHECKING:
    from raven.channels.base import BaseChannel
from raven.core.audit import audit_logger
from raven.core.channel_guardian import ChannelGuardian
from raven.core.failover import ModelFailover
from raven.core.llm import LLMRouter
from raven.core.logging import bind_context, clear_context
from raven.core.metrics import MetricsServer, metrics
from raven.core.models import IncomingMessage, Message
from raven.core.plugin_loader import PluginLoader
from raven.core.sandbox import Sandbox
from raven.core.security.context_filter import ContextVisibility, filter_context_by_visibility, redact_pii
from raven.core.security.rate_limiter import RateLimiter
from raven.core.security.sandbox_policy import (
    MAIN_SESSION_POLICY,
    get_policy_for_channel,
)
from raven.core.skills import Skill, skills_registry
from raven.core.task_engine.store import TaskStore
from raven.core.tracing import TracingManager, get_tracer


class Gateway:
    def __init__(self, db: Any, plugin_loader: PluginLoader, redis_url: str | None = None):
        self.db = db
        self._redis_url = redis_url
        self._redis_client: RedisClient | None = None
        self._session_store: SessionStore | None = None
        self._llm_cache: LLMCache | None = None
        self.llm = LLMRouter()
        self.failover = ModelFailover(self.llm)
        self.plugin_loader = plugin_loader
        self.channels = ChannelManager()
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._bg_semaphore = asyncio.Semaphore(100)
        self._running = False
        self.registry = AgentRegistry(db, self.llm, plugin_loader.tools)
        self.sandbox = Sandbox()
        self._skill_dirs: list[str] = []
        self._monitor_engine: Any = None
        self._rbac = RBAC()
        self._message_cb = CircuitBreaker("gateway.handle_message", failure_threshold=5, recovery_timeout=30.0)
        self._guardian = ChannelGuardian(on_channel_dead=self._on_channel_dead)
        self.mcp = MCPBridge(send_fn=self._send)
        self._metrics_server = MetricsServer(port=settings.metrics_port)
        self.event_bus = EventBus()
        self.features = FeatureFlags.get()
        self._tracing = TracingManager(service_name="raven-gateway", otlp_endpoint=settings.otlp_endpoint or None)
        self._tracer = get_tracer("raven.gateway")

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
        self._health = HealthMonitor(
            db_check=self.db.health_check,
            llm_check=self._llm_health_check,
            db_restart=self._db_restart,
            llm_restart=self._llm_restart,
        )
        self._llm_health_last_check = 0.0
        self._llm_health_result = True
        self._llm_health_ttl = 60.0
        self._rate_limiter = RateLimiter()
        self._redis_rate_limiter: RedisRateLimiter | None = None
        self._init_stores()
        self._extractor = EntityExtractor(llm_provider=self.llm)
        self._chunker = Chunker(max_chars=800, overlap=100)
        self._persister = get_persister()
        self.commands = CommandRegistry()
        self._register_commands()
        from raven.tools.register_all import create_tool_registry

        self._agent_orchestrator = AgentOrchestrator(
            llm=self.llm,
            tool_registry=create_tool_registry(),
            send_fn=lambda data: self._send("webchat", "orchestrator", data, streaming=True),
            max_total_iterations=50,
            max_handoffs=5,
        )
        self._message_processor = MessageProcessor(
            db=self.db,
            registry=self.registry,
            channels=self.channels,
            ctxmgr=self._ctxmgr,
            metrics=metrics,
            send_fn=self._send,
        )

    async def register_channel(self, channel: BaseChannel):
        await self.channels.register(channel)
        self._guardian.register(channel)
        await self.event_bus.publish("channel.registered", channel_id=channel.channel_id)

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

    def _init_stores(self) -> None:
        from raven.core.monitor.store import MonitorStore
        from raven.core.routine.store import RoutineStore

        self._monitor_store = MonitorStore(self.db.db_path)
        self._routine_store = RoutineStore(self.db.db_path)

    async def _extract_and_store(self, text: str, channel: str, user_id: str) -> None:
        try:
            result = await self._extractor.extract(text)
            if not result.entities:
                return
            chunks = self._chunker.chunk(text, strategy="semantic")
            doc_id = await self._persister.insert("messages", {
                "channel": channel,
                "user_id": user_id,
                "text": text[:500],
                "entity_count": len(result.entities),
                "chunk_count": len(chunks.chunks),
            })
            for entity in result.entities:
                await self._persister.insert("entities", {
                    "doc_id": doc_id,
                    "text": entity.text,
                    "label": entity.label,
                    "score": entity.score,
                })
        except Exception as exc:
            logger.debug("[services] extract_and_store failed: {}", exc)

    def _register_commands(self) -> None:
        from raven.core.gateway.commands.agent import AgentCommand, AgentStatusCommand
        from raven.core.gateway.commands.code import CodeCommand
        from raven.core.gateway.commands.compact import CompactCommand
        from raven.core.gateway.commands.help import HelpCommand
        from raven.core.gateway.commands.mcp import MCPCommand
        from raven.core.gateway.commands.monitor import MonitorCommand
        from raven.core.gateway.commands.new_session import NewSessionCommand
        from raven.core.gateway.commands.reset import ResetCommand
        from raven.core.gateway.commands.routine import RoutineCommand
        from raven.core.gateway.commands.settings import (
            ActivationCommand,
            RestartCommand,
            ThinkCommand,
            TraceCommand,
            UsageCommand,
            VerboseCommand,
        )
        from raven.core.gateway.commands.skills import SkillsCommand
        from raven.core.gateway.commands.status import StatusCommand
        from raven.core.gateway.commands.task import TaskCommand
        from raven.core.gateway.commands.voice import VoiceCommand

        self.commands.register(AgentCommand(self))
        self.commands.register(AgentStatusCommand(self))
        self.commands.register(StatusCommand(self))
        self.commands.register(NewSessionCommand(self))
        self.commands.register(ResetCommand(self))
        self.commands.register(CompactCommand(self))
        self.commands.register(ThinkCommand(self))
        self.commands.register(VerboseCommand(self))
        self.commands.register(TraceCommand(self))
        self.commands.register(UsageCommand(self))
        self.commands.register(RestartCommand(self))
        self.commands.register(ActivationCommand(self))
        self.commands.register(HelpCommand(self))
        self.commands.register(SkillsCommand(self))
        self.commands.register(TaskCommand(self))
        self.commands.register(MCPCommand(self))
        self.commands.register(MonitorCommand(self))
        self.commands.register(CodeCommand(self))
        self.commands.register(RoutineCommand(self))
        self.commands.register(VoiceCommand(self))

    async def start(self):
        if self._running:
            raise RuntimeError("Gateway already running")
        self.registry.setup_defaults()
        channel_count = len(await self.channels.list_ids())
        logger.info("Starting gateway with {} channels, {} agents", channel_count, len(self.registry.list_agents()))
        self._running = True
        started: list[str] = []

        if self._redis_url:
            logger.info("redis_url_configured_attempting_connection")
            self._redis_client = RedisClient(url=self._redis_url)
            is_connected = await self._redis_client.connect()
            if is_connected:
                logger.info("redis_connected_enabling_distributed_features")
                self._session_store = SessionStore(self._redis_client, ttl=3600)
                self._llm_cache = LLMCache(self._redis_client, ttl=300)
                self.llm = LLMRouter(llm_cache=self._llm_cache)
                self.failover = ModelFailover(self.llm)
                self._propagate_llm()
                self._redis_rate_limiter = RedisRateLimiter(self._redis_client, InMemoryRateLimiter())
            else:
                logger.warning("redis_connection_failed_falling_back_to_in_memory")
        else:
            logger.info("redis_not_configured_using_in_memory")

        try:
            await self._metrics_server.start()
            started.append("metrics")
            await self._tracing.start()
            started.append("tracing")
            await self.tasks.start()
            started.append("tasks")
            await self.channels.start_all()
            started.append("channels")
            self.load_skills()
            self._register_skill_handlers()
            self._health.register_checks()
            await self.mcp.start(plugin_loader=self.plugin_loader)
            started.append("mcp")
            await self._guardian.start()
            await self.event_bus.publish("gateway.started", channels=channel_count)
        except Exception:
            logger.error("Gateway start failed, rolling back {} components", len(started))
            await self._partial_stop(started)
            self._running = False
            raise

    async def _partial_stop(self, components: list[str]) -> None:
        if self._redis_client:
            try:
                await self._redis_client.disconnect()
            except Exception as e:
                logger.debug("redis stop during rollback: {}", e)
        if "guardian" in components:
            try:
                await self._guardian.stop()
            except Exception as e:
                logger.debug("guardian stop during rollback: {}", e)
        if "mcp" in components:
            try:
                await self.mcp.stop()
            except Exception as e:
                logger.debug("mcp stop during rollback: {}", e)
        if "channels" in components:
            try:
                await self.channels.stop_all()
            except Exception as e:
                logger.debug("channels stop during rollback: {}", e)
        if "tasks" in components:
            try:
                await self.tasks.stop()
            except Exception as e:
                logger.debug("tasks stop during rollback: {}", e)
        if "tracing" in components:
            try:
                await self._tracing.stop()
            except Exception as e:
                logger.debug("tracing stop during rollback: {}", e)
        if "metrics" in components:
            try:
                await self._metrics_server.stop()
            except Exception as e:
                logger.debug("metrics stop during rollback: {}", e)

    async def stop(self):
        if not self._running:
            logger.warning("Gateway already stopped")
            return
        logger.info("Stopping gateway...")
        self._running = False
        await self.event_bus.publish("gateway.stopping")
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()
        try:
            await self._guardian.stop()
        except Exception as e:
            logger.warning("guardian stop error: {}", e)
        if self._redis_client:
            try:
                await self._redis_client.disconnect()
            except Exception as e:
                logger.warning("redis disconnect error: {}", e)
        try:
            await self.tasks.stop()
        except Exception as e:
            logger.warning("tasks stop error: {}", e)
        try:
            await self.mcp.stop()
        except Exception as e:
            logger.warning("mcp stop error: {}", e)
        try:
            await self.channels.stop_all()
        except Exception as e:
            logger.warning("channels stop error: {}", e)
        try:
            await self._tracing.stop()
        except Exception as e:
            logger.warning("tracing stop error: {}", e)
        try:
            await self._metrics_server.stop()
        except Exception as e:
            logger.warning("metrics stop error: {}", e)
        try:
            await self._persister.close()
        except Exception as e:
            logger.warning("persister close error: {}", e)
        try:
            await self._monitor_store.close()
        except Exception as e:
            logger.warning("monitor store close error: {}", e)
        try:
            await self._routine_store.close()
        except Exception as e:
            logger.warning("routine store close error: {}", e)

    def _get_skill(self, name: str) -> Any:
        return skills_registry.get(name)

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

                tstore = self.tasks._store if self.tasks._store else TaskStore(self.db.db_path)
                try:
                    tasks = await tstore.list_tasks(user_id=user_id, limit=5)
                finally:
                    if tstore is not self.tasks._store:
                        await tstore.close()
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

    async def _llm_health_check(self) -> bool:
        now = time.monotonic()
        if now - self._llm_health_last_check < self._llm_health_ttl:
            return self._llm_health_result
        try:
            result = await self.llm.complete([{"role": "user", "content": "ping"}], model=settings.default_model)
            healthy = bool(result.content)
        except Exception as e:
            logger.warning("LLM health check failed: {}", e)
            healthy = False
        self._llm_health_last_check = now
        self._llm_health_result = healthy
        return healthy

    async def _db_restart(self) -> None:
        await self.db.disconnect()
        await self.db.connect()

    async def _llm_restart(self) -> None:
        self.llm = LLMRouter()
        self.failover = ModelFailover(self.llm)
        self._propagate_llm()
        self._llm_health_last_check = 0.0

    def _propagate_llm(self) -> None:
        self.registry.llm = self.llm
        self.tasks._llm = self.llm
        self._extractor._llm = self.llm
        self._agent_orchestrator._llm = self.llm
        if self._ctxmgr is not None:
            self._ctxmgr._llm = self.llm

    async def handle_message(self, event: IncomingMessage):
        if not self._running:
            logger.warning("Gateway not running, dropping message from {}[{}]", event.channel, event.user_id)
            return
        cid = str(uuid4())[:8]
        logger.info("[{}] Incoming message from {}[{}]: {}", cid, event.channel, event.user_id, event.text[:80])
        metrics.inc("messages_received", {"channel": event.channel})
        with self._tracer.start_as_current_span("handle_message") as span:
            span.set_attribute("channel", event.channel)
            span.set_attribute("user_id", event.user_id)
            span.set_attribute("session_id", event.session_id or "")
            span.set_attribute("message_id", cid)

            if not await self._rate_limiter.check_rate_limit(event.channel, event.user_id, channel_type=event.channel):
                metrics.inc("messages_rate_limited", {"channel": event.channel, "reason": "rate_limiter"})
                await self._send(event.channel, event.session_id, "Please slow down.")
                return

            if not await self._guardian.check_rate_limit(event.channel, event.user_id):
                metrics.inc("messages_rate_limited", {"channel": event.channel, "reason": "guardian"})
                await self._send(event.channel, event.session_id, "Please slow down.")
                return

            if self._redis_rate_limiter and not await self._redis_rate_limiter.is_allowed(
                f"msg:{event.channel}:{event.user_id}", 30, 60
            ):
                metrics.inc("messages_rate_limited", {"channel": event.channel, "reason": "distributed"})
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

    async def _bg_task(self, coro: Any) -> asyncio.Task[None]:
        await self._bg_semaphore.acquire()
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            self._bg_tasks.discard(t)
            self._bg_semaphore.release()
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("Background task failed: {}", exc)

        task.add_done_callback(_done)
        return task

    async def _handle_message_inner(self, event: IncomingMessage, cid: str = ""):
        bind_context(channel_id=event.channel, user_id=event.user_id, session_id=event.session_id or "")
        event.text = redact_pii(event.text)
        try:
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
            agent_profile = user.get("agent_profile", "") if isinstance(user, dict) else ""
            if agent_profile in ("architect", "planner", "coder", "reviewer", "debugger", "qa"):
                await self._handle_with_orchestrator(event, session_id, agent_profile)
            else:
                await self._message_processor.process(event, session_id)
        finally:
            clear_context()

        _t = await self._bg_task(self._extract_and_store(event.text, event.channel, event.user_id))

    async def _handle_with_orchestrator(self, event: IncomingMessage, session_id: str, profile: str) -> None:
        from raven.core.agents.orchestrator import StatusEmitter

        channel_obj = await self.channels.get(event.channel)
        send_stream = getattr(channel_obj, "send_stream", None) if channel_obj else None

        async def send_status(data: str) -> None:
            if send_stream is not None:
                from contextlib import suppress

                with suppress(Exception):
                    await send_stream(session_id, data)

        emitter = StatusEmitter(send_status if send_stream is not None else None)
        full_tokens: list[str] = []

        def on_token(t: str) -> None:
            full_tokens.append(t)

        try:
            result = await self._agent_orchestrator.execute(
                query=event.text,
                context={"additional_context": f"Channel: {event.channel}, User: {event.user_id}"},
                profile_override=profile,
                on_token=on_token,
                status_emitter=emitter,
            )
            response_text = "".join(full_tokens) or result.content
            if send_stream is not None and response_text:
                await self._send(event.channel, session_id, response_text, streaming=True)
            elif response_text:
                await self._send(event.channel, session_id, response_text)
            self._message_processor.metrics.inc("messages_sent", {"channel": event.channel})
        except Exception as e:
            logger.error("Orchestrator error for {}[{}]: {}", event.channel, event.user_id, e)
            await self._send(event.channel, session_id, "An error occurred while processing your request.")

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

    async def _handle_intent(self, event: IncomingMessage) -> bool:
        from raven.core.gateway.intents import handle_intent

        return await handle_intent(self, event)

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
                    await audit_logger.sensitive(
                        "pairing_approve", event.user_id, f"{event.channel}:{event.user_id}", True
                    )
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
        if not text or not text.startswith("/"):
            return False
        parts = text.split()
        cmd_name = parts[0][1:].lower()
        args = parts[1:] if len(parts) > 1 else []
        ctx = CommandContext(event=event, user=user, args=args)
        return await self.commands.execute(cmd_name, ctx)

    async def _on_channel_dead(self, channel_id: str) -> None:
        channel = await self.channels.remove(channel_id)
        if channel:
            logger.error("Channel {} removed from gateway (dead)", channel_id)
            metrics.inc("channels_dead", {"channel": channel_id})
            try:
                await channel.stop()
            except Exception as e:
                logger.error("Error stopping dead channel {}: {}", channel_id, e)
        remaining = await self.channels.list_ids()
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
        with self._tracer.start_as_current_span("send") as span:
            span.set_attribute("channel_id", channel_id)
            span.set_attribute("session_id", session_id)
            span.set_attribute("text_length", len(text))
            span.set_attribute("streaming", str(streaming))
            channel = await self.channels.get(channel_id)
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
