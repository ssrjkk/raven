from __future__ import annotations

from raven.automation.channel_router import (
    ChannelInfo,
    ChannelRouter,
    ChannelType,
    MessageNormalizer,
    MessagePriority,
    Notification,
    NormalizedMessage,
)


class TestChannelRouter:
    def setup_method(self) -> None:
        self.router = ChannelRouter()
        self.normalizer = MessageNormalizer()

    def test_channel_type_values(self) -> None:
        assert ChannelType.TELEGRAM.value == "telegram"
        assert ChannelType.DISCORD.value == "discord"
        assert ChannelType.SLACK.value == "slack"
        assert ChannelType.WEBCHAT.value == "webchat"
        assert ChannelType.EMAIL.value == "email"
        assert ChannelType.CONSOLE.value == "console"
        assert ChannelType.API.value == "api"
        assert ChannelType.VOICE.value == "voice"

    def test_message_priority_values(self) -> None:
        assert MessagePriority.LOW.value == 0
        assert MessagePriority.NORMAL.value == 1
        assert MessagePriority.HIGH.value == 2
        assert MessagePriority.CRITICAL.value == 3

    def test_normalize_telegram(self) -> None:
        msg = self.normalizer.normalize(
            "Hello <br> World",
            ChannelType.TELEGRAM,
            {"user_id": "u1", "user_name": "Alice"},
        )
        assert msg.text == "Hello \n World"
        assert msg.source_channel == ChannelType.TELEGRAM
        assert msg.user_id == "u1"
        assert msg.user_name == "Alice"

    def test_normalize_discord_strips_mentions(self) -> None:
        msg = self.normalizer.normalize(
            "Hey <@!123456> check <@789> this",
            ChannelType.DISCORD,
            {"user_id": "u2"},
        )
        assert "@" not in msg.text
        assert "Hey" in msg.text
        assert "check" in msg.text
        assert "this" in msg.text

    def test_normalize_email_strips_reply(self) -> None:
        raw = "Let's discuss\n\n> On Mon, Jan 1 wrote:\n> Old reply\n\nSounds good"
        msg = self.normalizer.normalize(raw, ChannelType.EMAIL)
        assert "> On" not in msg.text
        assert "Let's discuss" in msg.text
        assert "Sounds good" in msg.text

    def test_normalize_voice_collapses_whitespace(self) -> None:
        msg = self.normalizer.normalize(
            "  Hello    world   ", ChannelType.VOICE, {"user_id": "u3"}
        )
        assert msg.text == "Hello world"

    def test_register_and_unregister_channel(self) -> None:
        info = self.router.register_channel(ChannelType.TELEGRAM, "MyBot")
        assert info.channel_type == ChannelType.TELEGRAM
        assert info.name == "MyBot"
        assert info.priority == 2
        assert self.router.get_channel(ChannelType.TELEGRAM) is not None

        assert self.router.unregister_channel(ChannelType.TELEGRAM) is True
        assert self.router.get_channel(ChannelType.TELEGRAM) is None

    def test_register_existing_overwrites(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "first")
        self.router.register_channel(ChannelType.SLACK, "second", capabilities={"voice"})
        info = self.router.get_channel(ChannelType.SLACK)
        assert info is not None
        assert info.name == "second"
        assert "voice" in info.capabilities

    def test_route_message_basic(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        msg = NormalizedMessage(
            text="hello", source_channel=ChannelType.SLACK, user_id="u1"
        )
        routed = self.router.route_message(msg)
        assert routed == ChannelType.SLACK

    def test_route_message_with_critical_keyword(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        msg = NormalizedMessage(
            text="urgent security breach", source_channel=ChannelType.SLACK, user_id="u1"
        )
        routed = self.router.route_message(msg)
        assert routed is not None
        assert self.router._channel_affinity.get("u1") == ChannelType.SLACK

    def test_route_message_with_affinity(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        self.router.register_channel(ChannelType.TELEGRAM, "telegram-bot")
        self.router.set_affinity("u1", ChannelType.TELEGRAM)
        msg = NormalizedMessage(
            text="hello from slack", source_channel=ChannelType.SLACK, user_id="u1"
        )
        routed = self.router.route_message(msg)
        assert routed == ChannelType.TELEGRAM

    def test_route_message_no_registered_channels(self) -> None:
        msg = NormalizedMessage(
            text="hello", source_channel=ChannelType.CONSOLE, user_id="u1"
        )
        routed = self.router.route_message(msg)
        assert routed == ChannelType.CONSOLE

    def test_resume_context(self) -> None:
        self.router.register_channel(ChannelType.WEBCHAT, "webchat-instance")
        ctx = self.router.resume_context("u1", ChannelType.WEBCHAT)
        assert ctx.user_id == "u1"
        assert ctx.active_channel == ChannelType.WEBCHAT
        assert ctx.last_active > 0

    def test_evaluate_alerts(self) -> None:
        self.router.set_alert_rule({
            "keyword": "critical",
            "priority": MessagePriority.HIGH.value,
            "target_channels": ["telegram"],
            "reason": "critical alert triggered",
        })
        msg = NormalizedMessage(
            text="this is a critical error",
            source_channel=ChannelType.SLACK,
            user_id="u1",
        )
        notifications = self.router.evaluate_alerts(msg)
        assert len(notifications) == 1
        assert notifications[0].priority == MessagePriority.HIGH
        assert ChannelType.TELEGRAM in notifications[0].target_channels

    def test_evaluate_alerts_no_match(self) -> None:
        self.router.set_alert_rule({
            "keyword": "urgent",
            "priority": MessagePriority.NORMAL.value,
            "target_channels": [],
        })
        msg = NormalizedMessage(
            text="just a normal message",
            source_channel=ChannelType.CONSOLE,
            user_id="u2",
        )
        notifications = self.router.evaluate_alerts(msg)
        assert len(notifications) == 0

    def test_get_stats(self) -> None:
        self.router.register_channel(ChannelType.TELEGRAM, "bot")
        self.router.register_channel(ChannelType.DISCORD, "bot")
        stats = self.router.get_stats()
        assert stats["channels_registered"] == 2
        assert stats["channels_active"] == 2
        assert stats["active_contexts"] == 0
        assert stats["affinities_set"] == 0
        assert stats["alert_rules"] == 0
