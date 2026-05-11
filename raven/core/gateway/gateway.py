from __future__ import annotations
import random
import string
from uuid import uuid4
from typing import Any, Callable, Awaitable, TYPE_CHECKING
from loguru import logger
from raven.core.config import settings
if TYPE_CHECKING:
    from raven.channels.base import BaseChannel
from raven.core.db import Database
from raven.core.llm import LLMRouter
from raven.core.models import IncomingMessage, Message
from raven.core.agent.agent import Agent
from raven.core.agent.registry import AgentRegistry
from raven.core.failover import ModelFailover
from raven.core.sandbox import Sandbox, SandboxConfig
from raven.core.skills import SkillsRegistry, skills_registry, Skill
from raven.core.plugin_loader import PluginLoader
from raven.core.health import health
from raven.core.logging import audit, get_correlation_id
from raven.core.metrics import metrics


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
        self._register_health_checks()

    async def stop(self):
        logger.info("Stopping gateway...")
        self._running = False
        for cid, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Channel stopped: {}", cid)
            except Exception as e:
                logger.error("Error stopping channel {}: {}", cid, e)

    def _register_health_checks(self):
        async def _db_check():
            return await self.db.health_check()

        async def _llm_check():
            try:
                result = await self.llm.complete([{"role": "user", "content": "ping"}], model=settings.default_model)
                return bool(result.content)
            except Exception:
                return False

        health.register("database", _db_check, timeout=3.0, critical=True)
        health.register("llm", _llm_check, timeout=10.0, critical=False)

    async def handle_message(self, event: IncomingMessage):
        cid = get_correlation_id()
        logger.info("Incoming message from {}[{}]: {}", event.channel, event.user_id, event.text[:80])
        metrics.inc("messages_received", {"channel": event.channel})
        try:
            user = await self.db.find_or_create_user(event.channel, event.user_id)
            policy = settings.dm_policy

            if policy == "closed":
                if not user.get("is_allowed"):
                    metrics.inc("messages_blocked", {"channel": event.channel, "reason": "policy_closed"})
                    await self._send(event.channel, event.session_id, "Access denied. You are not authorized.")
                    return

            if policy == "pairing" and not user.get("is_allowed"):
                if event.text.startswith("/pair"):
                    code = event.text.split()[-1] if len(event.text.split()) > 1 else ""
                    matched = await self.db.get_user_by_pairing_code(code)
                    if matched and matched["id"] == user["id"]:
                        await self.db.set_user_allowed(user["id"], True)
                        await self.db.set_pairing_code(user["id"], "")
                        audit.sensitive_op(event.user_id, "pairing_approve", f"{event.channel}:{event.user_id}", True)
                        await self._send(event.channel, event.session_id, "You are now authorized!")
                        metrics.inc("pairing_approved", {"channel": event.channel})
                        return
                code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                await self.db.find_or_create_user(event.channel, event.user_id)
                await self.db.set_pairing_code(f"{event.channel}:{event.user_id}", code)
                await self._send(event.channel, event.session_id, f"Welcome! Your pairing code is: `{code}`\nPlease send `/pair {code}` to authorize.")
                metrics.inc("pairing_codes_sent", {"channel": event.channel})
                return

            handled = await self._handle_command(event)
            if handled:
                return

            session_id = event.session_id or f"{event.channel}:{event.user_id}:default"
            session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
            agent = self.registry.create_agent(session)

            event.text = self._clean_text(event.channel, event.text)

            skill_prompts = skills_registry.active_prompts(session.agent_skills or [])
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

    async def _handle_command(self, event: IncomingMessage) -> bool:
        text = event.text.strip()
        cmd = text.split()[0].lower() if text else ""

        if cmd == "/status":
            await self._send(event.channel, event.session_id, f"Raven AI is running. Channels: {', '.join(self.channels.keys())}")
            return True
        if cmd == "/new":
            session_id = f"{event.channel}:{event.user_id}:{uuid4().hex[:8]}"
            await self._send(event.channel, event.session_id, "Session reset.")
            return True
        if cmd == "/reset":
            await self._send(event.channel, event.session_id, "Session reset.")
            return True
        if cmd == "/help":
            await self._send(event.channel, event.session_id, (
                "Commands:\n"
                "/status - Show bot status\n"
                "/new - Start fresh conversation\n"
                "/reset - Reset current session\n"
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
