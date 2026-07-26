from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.config import settings
from raven.core.security.sandbox_policy import get_policy_for_channel

if TYPE_CHECKING:
    from raven.core.agent.registry import AgentRegistry
    from raven.core.context_window import ContextWindowManager
    from raven.core.db import Database
    from raven.core.gateway.channel_manager import ChannelManager
    from raven.core.metrics import MetricsCollector
    from raven.core.models import IncomingMessage


class MessageProcessor:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        channels: ChannelManager,
        ctxmgr: ContextWindowManager | None,
        metrics: MetricsCollector,
        send_fn: Callable[..., Any],
    ):
        self.db = db
        self.registry = registry
        self.channels = channels
        self._ctxmgr = ctxmgr
        self.metrics = metrics
        self._send = send_fn

    async def process(self, event: IncomingMessage, session_id: str) -> None:
        session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
        session.sandbox_policy = get_policy_for_channel(event.channel)

        await self._manage_context(session_id)

        agent = self.registry.create_agent(session)

        channel_obj = await self.channels.get(event.channel)
        supports_stream = hasattr(channel_obj, "send_stream") if channel_obj else False

        async def confirm_fn(tool_name: str, args: dict[str, Any]) -> bool:
            ch = await self.channels.get(event.channel)
            if not ch:
                return True
            action_desc = f"Execute tool '{tool_name}' with args: {str(args)[:200]}"
            result = await ch.ask_confirmation(event.user_id, action_desc, event.session_id or "")
            return bool(result)

        full_response = ""
        buffer = ""
        gen = agent.run(event.text, confirm_fn=confirm_fn)
        timed_out = False
        error_hint = ""
        try:
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
        except Exception:
            logger.exception("Message processing error mid-stream for session {}", session_id)
            self.metrics.inc("message_processing_errors", {"channel": event.channel})
            error_hint = "\n\n[⚠ Error occurred while processing. Partial response shown above.]"

        if timed_out:
            tail = "\n\n[⏱ Response timed out. Try rephrasing or splitting your request.]"
            full_response += tail
            if supports_stream:
                await self._send(event.channel, session_id, tail, streaming=True)

        if error_hint:
            full_response += error_hint
            if supports_stream:
                await self._send(event.channel, session_id, error_hint, streaming=True)

        if supports_stream and buffer:
            await self._send(event.channel, session_id, buffer, streaming=True)

        if full_response.strip():
            if not supports_stream:
                await self._send(event.channel, session_id, full_response, streaming=False)
            self.metrics.inc("messages_sent", {"channel": event.channel})
            self.metrics.observe("response_length", len(full_response), {"channel": event.channel})

    async def _manage_context(self, session_id: str) -> None:
        if self._ctxmgr is None:
            return

        msgs = await self.db.get_session_messages(session_id, limit=200)
        if not msgs:
            return

        msg_dicts = [{"role": m.role, "content": m.content} for m in msgs]
        total = await self._ctxmgr.estimate_tokens(msg_dicts)
        ratio = total / self._ctxmgr._config.max_tokens if self._ctxmgr._config.max_tokens > 0 else 0

        self.metrics.observe("context_window_pct", ratio * 100, {"session_id": session_id})

        if ratio < self._ctxmgr._config.warning_threshold:
            return

        logger.info(
            "Context at {:.1f}% for session {} ({} / {} tokens)",
            ratio * 100,
            session_id,
            total,
            self._ctxmgr._config.max_tokens,
        )
        self.metrics.inc("context_window_urgent", {"session_id": session_id})

        managed = await self._ctxmgr.manage(msg_dicts)
        if managed is not msg_dicts:
            await self.db.replace_session_messages(session_id, managed)
            self.metrics.inc("context_window_managed", {"session_id": session_id})
            logger.info(
                "Context window management applied for session {} ({:.1f}%)",
                session_id,
                ratio * 100,
            )
