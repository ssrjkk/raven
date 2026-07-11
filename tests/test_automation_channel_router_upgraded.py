from __future__ import annotations

import time

from raven.automation.channel_router import (
    ChannelInfo,
    ChannelRouter,
    ChannelType,
    MessageNormalizer,
    MessagePriority,
    NormalizedMessage,
    Notification,
)


class TestChannelRouterUpgraded:
    def setup_method(self) -> None:
        self.router = ChannelRouter()
        self.normalizer = MessageNormalizer()

    # --- Existing functionality ---

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

    # --- New functionality ---

    def test_get_context_sets_last_active(self) -> None:
        ctx = self.router._get_context("u_new")
        assert ctx.last_active > 0
        assert ctx.user_id == "u_new"

    async def test_continue_conversation_same_channel(self) -> None:
        self.router.resume_context("u1", ChannelType.TELEGRAM)
        ctx = await self.router.continue_conversation("u1", ChannelType.TELEGRAM, "hello again")
        assert ctx.active_channel == ChannelType.TELEGRAM
        assert len(ctx.history) == 1
        assert ctx.history[0].text == "hello again"
        assert "continuation_summary" not in ctx.metadata

    async def test_continue_conversation_cross_channel(self) -> None:
        self.router.resume_context("u1", ChannelType.TELEGRAM)
        ctx = await self.router.continue_conversation("u1", ChannelType.DISCORD, "switched to discord")
        assert ctx.active_channel == ChannelType.DISCORD
        assert ctx.metadata.get("continuation_summary") == "User continued from telegram to discord"
        assert len(ctx.history) == 1
        assert ctx.history[0].source_channel == ChannelType.DISCORD

    async def test_continue_conversation_cross_channel_preserves_prior_history(self) -> None:
        self.router.resume_context("u1", ChannelType.TELEGRAM)
        msg1 = NormalizedMessage(text="first", source_channel=ChannelType.TELEGRAM, user_id="u1")
        self.router._get_context("u1").history.append(msg1)
        ctx = await self.router.continue_conversation("u1", ChannelType.DISCORD, "second")
        assert len(ctx.history) == 2
        assert ctx.history[0].text == "first"
        assert ctx.history[0].source_channel == ChannelType.TELEGRAM
        assert ctx.history[1].text == "second"
        assert ctx.history[1].source_channel == ChannelType.DISCORD

    def test_get_conversation_summary_no_context(self) -> None:
        result = self.router.get_conversation_summary("nonexistent")
        assert result == []

    def test_get_conversation_summary_empty_history(self) -> None:
        self.router._get_context("u1")
        result = self.router.get_conversation_summary("u1")
        assert result == []

    def test_get_conversation_summary_returns_recent(self) -> None:
        ctx = self.router._get_context("u1")
        for i in range(5):
            ctx.history.append(NormalizedMessage(
                text=f"msg{i}", source_channel=ChannelType.TELEGRAM, user_id="u1"
            ))
        result = self.router.get_conversation_summary("u1", max_messages=3)
        assert len(result) == 3
        assert result[0]["text"] == "msg2"
        assert result[1]["text"] == "msg3"
        assert result[2]["text"] == "msg4"

    def test_get_conversation_summary_includes_channel_info(self) -> None:
        ctx = self.router._get_context("u1")
        ctx.history.append(NormalizedMessage(
            text="hey", source_channel=ChannelType.SLACK, user_id="u1", user_name="Bob"
        ))
        result = self.router.get_conversation_summary("u1")
        assert len(result) == 1
        assert result[0]["channel"] == "slack"
        assert result[0]["text"] == "hey"
        assert result[0]["user_name"] == "Bob"

    def test_detect_channel_switch_no_context(self) -> None:
        assert self.router.detect_channel_switch("nonexistent", ChannelType.TELEGRAM) is False

    def test_detect_channel_switch_no_active_channel(self) -> None:
        self.router._get_context("u1")
        assert self.router.detect_channel_switch("u1", ChannelType.TELEGRAM) is False

    def test_detect_channel_switch_same_channel(self) -> None:
        self.router.resume_context("u1", ChannelType.TELEGRAM)
        assert self.router.detect_channel_switch("u1", ChannelType.TELEGRAM) is False

    def test_detect_channel_switch_different_channel(self) -> None:
        self.router.resume_context("u1", ChannelType.TELEGRAM)
        assert self.router.detect_channel_switch("u1", ChannelType.DISCORD) is True

    async def test_route_message_with_context_no_switch(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        self.router.resume_context("u1", ChannelType.SLACK)
        msg = NormalizedMessage(
            text="hello", source_channel=ChannelType.SLACK, user_id="u1"
        )
        result = await self.router.route_message_with_context(msg, "u1")
        assert result["channel_switched"] is False
        assert result["routed_to"] == "slack"
        assert result["user_id"] == "u1"

    async def test_route_message_with_context_with_switch(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        self.router.register_channel(ChannelType.TELEGRAM, "telegram-bot")
        self.router.resume_context("u1", ChannelType.SLACK)
        msg = NormalizedMessage(
            text="now on telegram", source_channel=ChannelType.TELEGRAM, user_id="u1"
        )
        result = await self.router.route_message_with_context(msg, "u1")
        assert result["channel_switched"] is True
        assert result["routed_to"] == "telegram"
        context = result["context"]
        assert context.active_channel == ChannelType.TELEGRAM
        assert context.metadata.get("continuation_summary") == "User continued from slack to telegram"

    async def test_route_message_with_context_switch_then_back(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        self.router.register_channel(ChannelType.TELEGRAM, "telegram-bot")
        self.router.resume_context("u1", ChannelType.SLACK)
        msg1 = NormalizedMessage(
            text="switch to tg", source_channel=ChannelType.TELEGRAM, user_id="u1"
        )
        r1 = await self.router.route_message_with_context(msg1, "u1")
        assert r1["channel_switched"] is True
        assert r1["context"].active_channel == ChannelType.TELEGRAM
        msg2 = NormalizedMessage(
            text="back to slack", source_channel=ChannelType.SLACK, user_id="u1"
        )
        r2 = await self.router.route_message_with_context(msg2, "u1")
        assert r2["channel_switched"] is True
        assert r2["context"].active_channel == ChannelType.SLACK
        assert len(r2["context"].history) == 2

    async def test_route_message_with_context_preserves_history_after_switch(self) -> None:
        self.router.register_channel(ChannelType.SLACK, "slack-workspace")
        self.router.register_channel(ChannelType.TELEGRAM, "telegram-bot")
        self.router.resume_context("u1", ChannelType.SLACK)
        msg1 = NormalizedMessage(text="hello", source_channel=ChannelType.SLACK, user_id="u1")
        await self.router.route_message_with_context(msg1, "u1")
        msg2 = NormalizedMessage(text="world", source_channel=ChannelType.TELEGRAM, user_id="u1")
        r2 = await self.router.route_message_with_context(msg2, "u1")
        assert len(r2["context"].history) == 2
        assert r2["context"].history[0].text == "hello"
        assert r2["context"].history[1].text == "world"

    def test_prune_stale_contexts(self) -> None:
        ctx = self.router._get_context("u1")
        ctx.last_active = time.time() - 999999
        self.router._get_context("u2")
        pruned = self.router.prune_stale_contexts(max_age=3600)
        assert pruned == 1
        assert self.router.get_context("u1") is None
        assert self.router.get_context("u2") is not None
