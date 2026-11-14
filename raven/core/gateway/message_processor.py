from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.config import settings
from raven.core.security.context_filter import redact_pii
from raven.core.security.sandbox_policy import get_policy_for_channel

_SECRET_KEYS = ("api_key", "token", "secret", "password", "authorization", "cookie")


def _mask_tool_args(args: dict[str, Any]) -> str:
    def scrub(value: object) -> object:
        if isinstance(value, dict):
            return {
                k: ("***" if any(s in str(k).lower() for s in _SECRET_KEYS) else scrub(v)) for k, v in value.items()
            }
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            return redact_pii(value)
        return value

    return str(scrub(args))[:200]


if TYPE_CHECKING:
    from raven.core.agent.registry import AgentRegistry
    from raven.core.context_window import ContextWindowManager
    from raven.core.db import Database
    from raven.core.gateway.channel_manager import ChannelManager
    from raven.core.metrics import MetricsCollector
    from raven.core.models import IncomingMessage, Message


def usage_line(mode: str, totals: dict[str, int], rounds: int | None = None) -> str:
    """The `/usage` line the operator asked for, from the counters the run actually kept.

    `rounds` defaults to what the run recorded: a call that reuses the model five times says so
    rather than sounding like one request. A run that counts one total figure - the orchestrator
    reports tokens used, not a request/response split - prints that figure rather than a split of
    zeros, which would read as a request that cost nothing."""
    if mode not in ("tokens", "full"):
        return ""
    prompt = totals.get("prompt", 0)
    completion = totals.get("completion", 0)
    used = rounds if rounds is not None else totals.get("rounds", 0)
    if not prompt and not completion:
        line = f"[tokens: {totals.get('total', 0)} total]"
    else:
        line = f"[tokens: {prompt} in / {completion} out / {prompt + completion} total]"
    if mode == "full":
        line += f" · model calls: {used}"
    return line


class MessageProcessor:
    def __init__(
        self,
        db: Database,
        registry: AgentRegistry,
        channels: ChannelManager,
        ctxmgr: ContextWindowManager | None,
        metrics: MetricsCollector,
        send_fn: Callable[..., Any],
        get_pref_fn: Callable[[str, str, str, str], Any] | None = None,
    ):
        self.db = db
        self.registry = registry
        self.channels = channels
        self._ctxmgr = ctxmgr
        self.metrics = metrics
        self._send = send_fn
        self._get_pref = get_pref_fn

    async def process(self, event: IncomingMessage, session_id: str) -> None:
        session = await self.db.get_or_create_session(session_id, event.channel, event.user_id)
        session.sandbox_policy = get_policy_for_channel(event.channel)

        msgs = await self.db.get_session_messages(session_id, limit=200)

        managed = await self._manage_context(session_id, msgs)
        history = [{"role": m["role"], "content": m["content"]} for m in managed]

        self._last_agent = agent = self.registry.create_agent(session)
        agent.priority = event.priority
        await self._apply_prefs(agent, event)

        channel_obj = await self.channels.get(event.channel)
        supports_stream = hasattr(channel_obj, "send_stream") if channel_obj else False

        async def confirm_fn(tool_name: str, args: dict[str, Any]) -> bool:
            ask = getattr(channel_obj, "ask_confirmation", None)
            if ask is None:
                logger.warning("Channel '{}' cannot confirm '{}' — denied, not auto-approved", event.channel, tool_name)
                return False
            action_desc = f"Execute tool '{tool_name}' with args: {_mask_tool_args(args)}"
            return bool(await ask(event.user_id, action_desc, event.session_id or ""))

        full_response = ""
        buffer = ""
        gen = agent.run(event.text, confirm_fn=confirm_fn, history=history)
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
        finally:
            try:
                await gen.aclose()  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug("Failed to close agent generator for session {}: {}", session_id, e)

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
            line = await self._usage_line(event)
            if line:
                await self._send(event.channel, session_id, line, streaming=False)

    async def _apply_prefs(self, agent: Any, event: IncomingMessage) -> None:
        """`/verbose`, `/trace` and `/think` are read by the run, so they have to be on the agent
        before the first token is asked for. Defaults match what the commands report."""
        if self._get_pref is None:
            return
        verbose = await self._get_pref(event.channel, event.user_id, "verbose", "off")
        trace = await self._get_pref(event.channel, event.user_id, "trace", "off")
        agent.show_tool_progress = verbose == "on"
        agent.trace = trace == "on"
        agent.think_level = await self._get_pref(event.channel, event.user_id, "think_level", "high")

    async def _usage_line(self, event: IncomingMessage) -> str:
        """`/usage` is per user and per channel; the run had the numbers, the pref says whether
        to show them. Sent as its own message so the stored history keeps the model's answer."""
        if self._get_pref is None:
            return ""
        mode = await self._get_pref(event.channel, event.user_id, "usage_mode", "off")
        totals = getattr(self._last_agent, "usage_totals", {}) if hasattr(self, "_last_agent") else {}
        return usage_line(mode, totals)

    async def _manage_context(self, session_id: str, msgs: list[Message]) -> list[dict[str, Any]]:
        if self._ctxmgr is None:
            return [{"role": m.role, "content": m.content} for m in msgs]

        if not msgs:
            return []

        msg_dicts = [
            {"role": m.role, "content": m.content, "created_at": m.created_at, "metadata": m.metadata} for m in msgs
        ]
        total = await self._ctxmgr.estimate_tokens(msg_dicts)
        ratio = total / self._ctxmgr._config.max_tokens if self._ctxmgr._config.max_tokens > 0 else 0

        self.metrics.observe("context_window_pct", ratio * 100)

        if ratio < self._ctxmgr._config.warning_threshold:
            return msg_dicts

        logger.info(
            "Context at {:.1f}% for session {} ({} / {} tokens)",
            ratio * 100,
            session_id,
            total,
            self._ctxmgr._config.max_tokens,
        )
        self.metrics.inc("context_window_urgent")

        managed = await self._ctxmgr.manage(msg_dicts)
        if managed is not msg_dicts:
            await self.db.replace_session_messages(session_id, managed)
            self.metrics.inc("context_window_managed")
            logger.info(
                "Context window management applied for session {} ({:.1f}%)",
                session_id,
                ratio * 100,
            )
        return managed
