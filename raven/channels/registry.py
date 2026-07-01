from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger

from raven.channels.base import BaseChannel

ChannelFactory = Callable[[], BaseChannel]


class ChannelRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ChannelFactory] = {}
        self._instances: dict[str, BaseChannel] = {}
        self._aliases: dict[str, str] = {}

    def register(self, name: str, factory: ChannelFactory, alias: str | None = None) -> None:
        self._factories[name] = factory
        if alias:
            self._aliases[alias] = name
        logger.info("Channel registered: {} (alias: {})", name, alias or "—")

    def get(self, name: str) -> BaseChannel | None:
        canonical = self._aliases.get(name, name)
        if canonical not in self._instances and canonical in self._factories:
            self._instances[canonical] = self._factories[canonical]()
        return self._instances.get(canonical)

    def create(self, name: str) -> BaseChannel | None:
        canonical = self._aliases.get(name, name)
        if canonical in self._factories:
            return self._factories[canonical]()
        return None

    def list_available(self) -> list[str]:
        return list(self._factories.keys())

    def list_active(self) -> list[str]:
        return list(self._instances.keys())

    def remove(self, name: str) -> None:
        canonical = self._aliases.get(name, name)
        self._instances.pop(canonical, None)

    def start_all(self) -> None:
        for name in self._factories:
            channel = self.get(name)
            if channel and channel not in self._instances.values():
                self._instances[name] = channel

    def stop_all(self) -> None:
        for name, channel in self._instances.items():
            try:
                import asyncio
                asyncio.ensure_future(channel.stop())
            except Exception as exc:
                logger.error("Failed to stop channel {}: {}", name, exc)
        self._instances.clear()


_channel_registry: ChannelRegistry | None = None


def get_channel_registry() -> ChannelRegistry:
    global _channel_registry
    if _channel_registry is None:
        _channel_registry = ChannelRegistry()
    return _channel_registry


CHANNEL_MAP: dict[str, str] = {
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "Slack",
    "whatsapp": "WhatsApp Business",
    "signal": "Signal",
    "matrix": "Matrix",
    "googlechat": "Google Chat",
    "irc": "IRC",
    "teams": "Microsoft Teams",
    "feishu": "Feishu/Lark",
    "line": "LINE",
    "webchat": "Web Chat",
    "wechat": "WeChat (coming)",
    "qq": "QQ (coming)",
    "imessage": "iMessage (coming)",
    "macos": "macOS Menu Bar (coming)",
    "ios": "iOS App (coming)",
    "android": "Android App (coming)",
    "windows": "Windows Hub (coming)",
    "email": "Email/IMAP (coming)",
    "sms": "SMS/Twilio (coming)",
    "mattermost": "Mattermost (coming)",
    "zulip": "Zulip (coming)",
    "rocketchat": "Rocket.Chat (coming)",
    "facebook": "Facebook Messenger (coming)",
    "instagram": "Instagram DM (coming)",
    "viber": "Viber (coming)",
}


def register_default_channels(registry: ChannelRegistry) -> None:
    from raven.channels.discord.channel import DiscordChannel
    from raven.channels.feishu.channel import FeishuChannel
    from raven.channels.googlechat.channel import GoogleChatChannel
    from raven.channels.irc.channel import IRCChannel
    from raven.channels.line.channel import LINECChannel
    from raven.channels.matrix.channel import MatrixChannel
    from raven.channels.slack.channel import SlackChannel
    from raven.channels.teams.channel import TeamsChannel
    from raven.channels.telegram.channel import TelegramChannel
    from raven.channels.whatsapp.channel import WhatsAppChannel

    registry.register("telegram", lambda: TelegramChannel())
    registry.register("discord", lambda: DiscordChannel())
    registry.register("slack", lambda: SlackChannel())
    registry.register("whatsapp", lambda: WhatsAppChannel())
    registry.register("signal", lambda: SignalChannelStub())
    registry.register("matrix", lambda: MatrixChannel())
    registry.register("googlechat", lambda: GoogleChatChannel())
    registry.register("irc", lambda: IRCChannel())
    registry.register("teams", lambda: TeamsChannel())
    registry.register("feishu", lambda: FeishuChannel())
    registry.register("line", lambda: LINECChannel())
    registry.register("webchat", lambda: WebChatChannelStub())


class SignalChannelStub(BaseChannel):
    channel_id = "signal"
    async def connect(self) -> None: logger.info("[signal] stub connect")
    async def disconnect(self) -> None: logger.info("[signal] stub disconnect")
    async def send(self, session_id: str, message: Any) -> None: logger.info("[signal] stub send")
    async def on_message(self, handler: Any) -> None: logger.info("[signal] stub on_message")
    async def start(self) -> None: logger.info("[signal] stub start")
    async def stop(self) -> None: logger.info("[signal] stub stop")


class WebChatChannelStub(BaseChannel):
    channel_id = "webchat"
    async def connect(self) -> None: logger.info("[webchat] stub connect")
    async def disconnect(self) -> None: logger.info("[webchat] stub disconnect")
    async def send(self, session_id: str, message: Any) -> None: logger.info("[webchat] stub send")
    async def on_message(self, handler: Any) -> None: logger.info("[webchat] stub on_message")
    async def start(self) -> None: logger.info("[webchat] stub start")
    async def stop(self) -> None: logger.info("[webchat] stub stop")
