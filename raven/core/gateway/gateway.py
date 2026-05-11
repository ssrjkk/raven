from __future__ import annotations
import random
import string
from typing import Any, Callable, Awaitable
from loguru import logger
from raven.core.config import settings
from raven.core.db import Database
from raven.core.llm import LLMRouter
from raven.core.models import IncomingMessage, Message
from raven.core.agent.agent import Agent
from raven.core.agent.registry import AgentRegistry
from raven.core.plugin_loader import PluginLoader


class Gateway:
    def __init__(self, db: Database, plugin_loader: PluginLoader):
        self.db = db
        self.llm = LLMRouter()
        self.plugin_loader = plugin_loader
        self.channels: dict[str, Any] = {}
        self._running = False
        self.registry = AgentRegistry(db, self.llm, plugin_loader.tools)

    def register_channel(self, channel: BaseChannel):
        self.channels[channel.channel_id] = channel
        logger.info("Registered channel: {}", channel.channel_id)

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

    async def stop(self):
        logger.info("Stopping gateway...")
        self._running = False
        for cid, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Channel stopped: {}", cid)
            except Exception as e:
                logger.error("Error stopping channel {}: {}", cid, e)

    async def handle_message(self, event: IncomingMessage):
        logger.info("Incoming message from {}[{}]: {}", event.channel, event.user_id, event.text[:80])
        try:
            user = await self.db.find_or_create_user(event.channel, event.user_id)
            policy = settings.dm_policy

            if policy == "closed":
                if not user.get("is_allowed"):
                    await self._send(event.channel, event.session_id, "Access denied. You are not authorized.")
                    return

            if policy == "pairing" and not user.get("is_allowed"):
                if event.text.startswith("/pair"):
                    code = event.text.split()[-1] if len(event.text.split()) > 1 else ""
                    matched = await self.db.get_user_by_pairing_code(code)
                    if matched and matched["id"] == user["id"]:
                        await self.db.set_user_allowed(user["id"], True)
                        await self.db.set_pairing_code(user["id"], "")
                        await self._send(event.channel, event.session_id, "You are now authorized!")
                        return
                code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                await self.db.find_or_create_user(event.channel, event.user_id)
                await self.db.set_pairing_code(f"{event.channel}:{event.user_id}", code)
                await self._send(event.channel, event.session_id, f"Welcome! Your pairing code is: `{code}`\nPlease send `/pair {code}` to authorize.")
                return

            session_id = event.session_id or f"{event.channel}:{event.user_id}:default"
            session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
            agent = self.registry.create_agent(session)

            event.text = self._clean_text(event.channel, event.text)

            full_response = ""
            async for token in agent.run(event.text):
                full_response += token

            if full_response.strip():
                await self._send(event.channel, session_id, full_response)

        except Exception as e:
            logger.error("handle_message error: {}", e)
            await self._send(event.channel, event.session_id, f"Sorry, an error occurred: {str(e)[:200]}")

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
