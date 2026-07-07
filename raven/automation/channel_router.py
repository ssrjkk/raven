from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

try:
    from raven.channels.base import BaseChannel
    from raven.channels.registry import ChannelRegistry, get_channel_registry

    _CHANNELS_AVAILABLE = True
except ImportError:
    BaseChannel = None  # type: ignore[assignment,misc]
    ChannelRegistry = None  # type: ignore[assignment,misc]
    get_channel_registry = None  # type: ignore[assignment]

    _CHANNELS_AVAILABLE = False


class ChannelType(Enum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WEBCHAT = "webchat"
    EMAIL = "email"
    CONSOLE = "console"
    API = "api"
    VOICE = "voice"


class MessagePriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class NormalizedMessage:
    text: str
    source_channel: ChannelType
    user_id: str
    user_name: str = ""
    thread_id: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0


@dataclass
class ChannelInfo:
    channel_type: ChannelType
    name: str
    priority: int = 0
    capabilities: set[str] = field(default_factory=lambda: {"text", "files"})
    context: dict[str, Any] = field(default_factory=dict)
    active: bool = True


@dataclass
class Notification:
    message: NormalizedMessage
    priority: MessagePriority
    reason: str = ""
    target_channels: list[ChannelType] = field(default_factory=list)


@dataclass
class ChannelContext:
    user_id: str
    active_channel: ChannelType | None = None
    history: list[NormalizedMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_active: float = 0.0


def discover_channels() -> dict[str, type[BaseChannel]]:
    channels: dict[str, type[BaseChannel]] = {}
    if not _CHANNELS_AVAILABLE:
        logger.debug("[router] channels not available for discovery")
        return channels

    try:
        from raven.channels import (
            DiscordChannel,
            FeishuChannel,
            GoogleChatChannel,
            IRCChannel,
            LINECChannel,
            MatrixChannel,
            SignalChannel,
            SlackChannel,
            TeamsChannel,
            TelegramChannel,
            WebChatChannel,
            WhatsAppChannel,
        )
        for cls in (
            DiscordChannel,
            FeishuChannel,
            GoogleChatChannel,
            IRCChannel,
            LINECChannel,
            MatrixChannel,
            SignalChannel,
            SlackChannel,
            TeamsChannel,
            TelegramChannel,
            WebChatChannel,
            WhatsAppChannel,
        ):
            name = getattr(cls, "channel_id", cls.__name__.lower().replace("channel", ""))
            channels[name] = cls
    except ImportError as exc:
        logger.debug("[router] could not discover channels: {}", exc)

    return channels


async def route_to_channel(channel_type: ChannelType, message: NormalizedMessage) -> bool:
    if not _CHANNELS_AVAILABLE:
        logger.debug("[router] channels not available, skipping route_to_channel")
        return False

    try:
        registry = get_channel_registry()
        channel_name = channel_type.value
        channel = registry.get(channel_name)
        if channel is None:
            logger.warning("[router] no channel instance for '{}'", channel_name)
            return False

        from raven.core.models import Message
        msg = Message(
            session_id=message.user_id,
            role="user",
            content=message.text,
            metadata={
                "user_id": message.user_id,
                "user_name": message.user_name,
                "thread_id": message.thread_id,
                "source_channel": channel_type.value,
                "attachments": message.attachments,
                **message.metadata,
            },
        )
        await channel.send(message.user_id, msg)
        logger.info("[router] routed message to channel '{}'", channel_name)
        return True
    except Exception as exc:
        logger.warning("[router] failed to route to channel '{}': {}", channel_type.value, exc)
        return False


def get_channel_stats() -> dict[str, Any]:
    if not _CHANNELS_AVAILABLE:
        return {"available": False, "channels": 0, "message": "channels not available"}

    try:
        registry = get_channel_registry()
        available = registry.list_available()
        active = registry.list_active()
        return {
            "available": True,
            "channels": len(available),
            "available_list": available,
            "active_list": active,
            "active_count": len(active),
        }
    except Exception as exc:
        logger.warning("[router] failed to get channel stats: {}", exc)
        return {"available": False, "error": str(exc)}


class MessageNormalizer:
    _MARKDOWN_STRIP = re.compile(r"[*_~`#>{}-]+")

    def __init__(self) -> None:
        self._normalizers: dict[ChannelType, Any] = {}

    def normalize(self, raw: str, channel: ChannelType, metadata: dict[str, Any] | None = None) -> NormalizedMessage:
        text = self._normalize_text(raw, channel)
        timestamp = time.time()
        uid = metadata.get("user_id", "unknown") if metadata else "unknown"
        uname = metadata.get("user_name", "") if metadata else ""
        tid = metadata.get("thread_id", "") if metadata else ""
        attachments = self._extract_attachments(text, channel)
        return NormalizedMessage(
            text=text,
            source_channel=channel,
            user_id=uid,
            user_name=uname,
            thread_id=tid,
            attachments=attachments,
            metadata=metadata or {},
            timestamp=timestamp,
        )

    def _normalize_text(self, raw: str, channel: ChannelType) -> str:
        text = raw.strip()
        if channel == ChannelType.TELEGRAM:
            text = text.replace("<br>", "\n")
        elif channel == ChannelType.DISCORD:
            text = text.replace("<br>", "\n")
            text = self._strip_discord_mentions(text)
        elif channel == ChannelType.SLACK:
            text = self._strip_slack_formatting(text)
        elif channel == ChannelType.EMAIL:
            text = self._strip_email_reply(text)
        elif channel == ChannelType.VOICE:
            text = self._normalize_voice(text)
        return text

    def _strip_discord_mentions(self, text: str) -> str:
        return re.sub(r"<@!?\d+>", "", text).strip()

    def _strip_slack_formatting(self, text: str) -> str:
        text = re.sub(r"<@[A-Z0-9]+>", "", text)
        return text.strip()

    def _strip_email_reply(self, text: str) -> str:
        lines = text.splitlines()
        clean: list[str] = []
        for line in lines:
            if line.startswith(">") or line.startswith("On ") and " wrote:" in line:
                continue
            clean.append(line)
        return "\n".join(clean).strip()

    def _normalize_voice(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _extract_attachments(self, text: str, channel: ChannelType) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        url_pattern = re.compile(r"https?://[^\s]+")
        for match in url_pattern.finditer(text):
            url = match.group(0)
            attachments.append({"type": "url", "url": url, "original_channel": channel.value})
        return attachments


class ChannelRouter:
    def __init__(self) -> None:
        self._channels: dict[ChannelType, ChannelInfo] = {}
        self._contexts: dict[str, ChannelContext] = {}
        self._normalizer = MessageNormalizer()
        self._channel_affinity: dict[str, ChannelType] = {}
        self._alert_rules: list[Any] = []
        self._priority_boost: dict[ChannelType, int] = {
            ChannelType.TELEGRAM: 2,
            ChannelType.DISCORD: 1,
            ChannelType.SLACK: 1,
            ChannelType.WEBCHAT: 0,
            ChannelType.EMAIL: 0,
            ChannelType.CONSOLE: -1,
            ChannelType.API: 1,
            ChannelType.VOICE: 0,
        }
        self._channel_stats: dict[str, int] = {}

    def register_channel(self, channel_type: ChannelType, name: str, capabilities: set[str] | None = None, metadata: dict[str, Any] | None = None) -> ChannelInfo:
        info = ChannelInfo(
            channel_type=channel_type,
            name=name,
            priority=self._priority_boost.get(channel_type, 0),
            capabilities=capabilities or {"text", "files"},
            context=metadata or {},
        )
        self._channels[channel_type] = info
        logger.info("[router] registered channel {} ({})", name, channel_type.value)
        return info

    def unregister_channel(self, channel_type: ChannelType) -> bool:
        removed = self._channels.pop(channel_type, None)
        if removed:
            logger.info("[router] unregistered channel {} ({})", removed.name, channel_type.value)
        return removed is not None

    def get_available_channels(self) -> list[ChannelInfo]:
        return [c for c in self._channels.values() if c.active]

    def route_message(self, message: NormalizedMessage) -> ChannelType | None:
        context = self._get_context(message.user_id)
        context.history.append(message)
        context.last_active = time.time()
        context.active_channel = message.source_channel

        if self._needs_critical_reroute(message):
            best = self._find_best_channel(message.user_id, message)
            if best:
                logger.info("[router] rerouting critical message from {} to {}", message.source_channel.value, best.value)
                self._channel_affinity[message.user_id] = best
                return best

        affinity = self._channel_affinity.get(message.user_id)
        if affinity and affinity in self._channels and self._channels[affinity].active:
            return affinity

        return message.source_channel

    def _needs_critical_reroute(self, message: NormalizedMessage) -> bool:
        keywords = {"urgent", "critical", "emergency", "asap", "immediately", "security", "breach", "downtime"}
        text_lower = message.text.lower()
        return any(kw in text_lower for kw in keywords)

    def _find_best_channel(self, user_id: str, message: NormalizedMessage) -> ChannelType | None:
        candidates = self.get_available_channels()
        if not candidates:
            return None

        context = self._get_context(user_id)
        if context.active_channel and self._channels.get(context.active_channel, ChannelInfo(ChannelType.CONSOLE, "")).active:
            return context.active_channel

        scored = sorted(
            candidates,
            key=lambda c: (
                c.priority,
                c.channel_type == ChannelType.TELEGRAM,
                c.channel_type == ChannelType.DISCORD,
            ),
            reverse=True,
        )
        return scored[0].channel_type if scored else None

    def resume_context(self, user_id: str, channel: ChannelType) -> ChannelContext:
        context = self._get_context(user_id)
        context.active_channel = channel
        context.last_active = time.time()
        logger.debug("[router] resumed context for {} on {}", user_id, channel.value)
        return context

    def set_affinity(self, user_id: str, channel_type: ChannelType) -> None:
        self._channel_affinity[user_id] = channel_type
        logger.info("[router] affinity set: {} -> {}", user_id, channel_type.value)

    def clear_affinity(self, user_id: str) -> None:
        self._channel_affinity.pop(user_id, None)

    def get_channel_priority(self, channel_type: ChannelType) -> int:
        return self._priority_boost.get(channel_type, 0)

    def set_channel_priority(self, channel_type: ChannelType, priority: int) -> None:
        self._priority_boost[channel_type] = priority
        if channel_type in self._channels:
            self._channels[channel_type].priority = priority

    def normalize_message(self, raw: str, channel: ChannelType, metadata: dict[str, Any] | None = None) -> NormalizedMessage:
        return self._normalizer.normalize(raw, channel, metadata)

    def get_context(self, user_id: str) -> ChannelContext | None:
        return self._contexts.get(user_id)

    def _get_context(self, user_id: str) -> ChannelContext:
        if user_id not in self._contexts:
            self._contexts[user_id] = ChannelContext(user_id=user_id)
        self._contexts[user_id].last_active = time.time()
        return self._contexts[user_id]

    async def continue_conversation(self, user_id: str, new_channel: ChannelType, message_text: str) -> ChannelContext:
        context = self._get_context(user_id)
        old_channel = context.active_channel

        if old_channel is not None and old_channel != new_channel:
            summary = f"User continued from {old_channel.value} to {new_channel.value}"
            context.metadata["continuation_summary"] = summary
            logger.info("[router] cross-channel continuation: {} ({} -> {})", user_id, old_channel.value, new_channel.value)

        norm_msg = self.normalize_message(message_text, new_channel, {"user_id": user_id})
        context.history.append(norm_msg)
        context.active_channel = new_channel
        context.last_active = time.time()

        return context

    def get_conversation_summary(self, user_id: str, max_messages: int = 10) -> list[dict[str, Any]]:
        context = self._contexts.get(user_id)
        if not context or not context.history:
            return []

        recent = context.history[-max_messages:]
        return [
            {
                "channel": msg.source_channel.value,
                "text": msg.text,
                "user_id": msg.user_id,
                "user_name": msg.user_name,
                "timestamp": msg.timestamp,
            }
            for msg in recent
        ]

    def detect_channel_switch(self, user_id: str, channel_type: ChannelType) -> bool:
        context = self._contexts.get(user_id)
        if context is None or context.active_channel is None:
            return False
        return context.active_channel != channel_type

    async def route_message_with_context(self, message: NormalizedMessage, user_id: str) -> dict[str, Any]:
        norm_msg = self.normalize_message(message.text, message.source_channel, {
            "user_id": user_id,
            "user_name": message.user_name,
            "thread_id": message.thread_id,
        })
        channel_switched = self.detect_channel_switch(user_id, norm_msg.source_channel)

        if channel_switched:
            context = await self.continue_conversation(user_id, norm_msg.source_channel, norm_msg.text)
        else:
            context = self._get_context(user_id)
            context.history.append(norm_msg)
            context.active_channel = norm_msg.source_channel
            context.last_active = time.time()

        if self._needs_critical_reroute(norm_msg):
            best = self._find_best_channel(user_id, norm_msg)
            if best:
                logger.info("[router] rerouting critical message from {} to {}", norm_msg.source_channel.value, best.value)
                self._channel_affinity[user_id] = best
                routed = best
            else:
                routed = norm_msg.source_channel
        else:
            affinity = self._channel_affinity.get(user_id)
            if affinity and affinity in self._channels and self._channels[affinity].active:
                routed = affinity
            else:
                routed = norm_msg.source_channel

        return {
            "user_id": user_id,
            "channel_switched": channel_switched,
            "routed_to": routed.value if routed else None,
            "context": context,
            "message": norm_msg,
        }

    def prune_stale_contexts(self, max_age: float = 86400.0) -> int:
        now = time.time()
        stale = [uid for uid, ctx in self._contexts.items() if now - ctx.last_active > max_age]
        for uid in stale:
            del self._contexts[uid]
        if stale:
            logger.info("[router] pruned {} stale contexts", len(stale))
        return len(stale)

    def set_alert_rule(self, rule: dict[str, Any]) -> None:
        self._alert_rules.append(rule)

    def evaluate_alerts(self, message: NormalizedMessage) -> list[Notification]:
        notifications: list[Notification] = []
        for rule in self._alert_rules:
            keyword = rule.get("keyword", "")
            if keyword and keyword.lower() in message.text.lower():
                priority = MessagePriority(rule.get("priority", MessagePriority.NORMAL.value))
                target_types = [ChannelType(t) for t in rule.get("target_channels", [])] if rule.get("target_channels") else [message.source_channel]
                notifications.append(Notification(
                    message=message,
                    priority=priority,
                    reason=rule.get("reason", f"matched keyword '{keyword}'"),
                    target_channels=target_types,
                ))
        return notifications

    def get_stats(self) -> dict[str, Any]:
        return {
            "channels_registered": len(self._channels),
            "channels_active": sum(1 for c in self._channels.values() if c.active),
            "active_contexts": len(self._contexts),
            "affinities_set": len(self._channel_affinity),
            "alert_rules": len(self._alert_rules),
            **get_channel_stats(),
        }

    def get_channel(self, channel_type: ChannelType) -> ChannelInfo | None:
        return self._channels.get(channel_type)

    async def send_message(self, channel_type: ChannelType, message: NormalizedMessage) -> bool:
        self._increment_stat(channel_type.value)
        routed_type = self.route_message(message)
        target = routed_type or channel_type

        success = await route_to_channel(target, message)
        if success:
            logger.info("[router] send_message delivered to '{}'", target.value)
        else:
            logger.debug("[router] send_message to '{}' used simulated delivery", target.value)
        return success

    def get_route_stats(self) -> dict[str, int]:
        return dict(self._channel_stats)

    def _increment_stat(self, channel_name: str) -> None:
        self._channel_stats[channel_name] = self._channel_stats.get(channel_name, 0) + 1
