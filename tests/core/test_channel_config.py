from __future__ import annotations

import os

from raven.core.channel_config import (
    all_channel_names,
    configured_channels,
    get_channel_config,
    has_any_channel,
)


def test_get_channel_config_telegram():
    os.environ["TELEGRAM_BOT_TOKEN"] = "tok123"
    try:
        cfg = get_channel_config("telegram")
        assert cfg.get("bot_token") == "tok123"
    finally:
        del os.environ["TELEGRAM_BOT_TOKEN"]


def test_get_channel_config_slack():
    os.environ["SLACK_BOT_TOKEN"] = "xoxb-abc"
    os.environ["SLACK_SIGNING_SECRET"] = "secret456"
    try:
        cfg = get_channel_config("slack")
        assert cfg.get("bot_token") == "xoxb-abc"
        assert cfg.get("signing_secret") == "secret456"
    finally:
        del os.environ["SLACK_BOT_TOKEN"]
        del os.environ["SLACK_SIGNING_SECRET"]


def test_get_channel_config_irc():
    os.environ["IRC_SERVER"] = "irc.libera.chat"
    os.environ["IRC_PORT"] = "6667"
    os.environ["IRC_NICK"] = "raven-bot"
    os.environ["IRC_PASSWORD"] = "hunter2"
    os.environ["IRC_CHANNELS"] = "#raven,#test"
    try:
        cfg = get_channel_config("irc")
        assert cfg.get("server") == "irc.libera.chat"
        assert cfg.get("port") == "6667"
        assert cfg.get("nick") == "raven-bot"
        assert cfg.get("password") == "hunter2"
        assert cfg.get("channels") == "#raven,#test"
    finally:
        del os.environ["IRC_SERVER"]
        del os.environ["IRC_PORT"]
        del os.environ["IRC_NICK"]
        del os.environ["IRC_PASSWORD"]
        del os.environ["IRC_CHANNELS"]


def test_has_any_channel_true():
    os.environ["DISCORD_BOT_TOKEN"] = "discord-tok"
    try:
        assert has_any_channel("discord") is True
    finally:
        del os.environ["DISCORD_BOT_TOKEN"]


def test_has_any_channel_false():
    name = "telegram"
    original = os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    try:
        assert has_any_channel(name) is False
    finally:
        if original is not None:
            os.environ["TELEGRAM_BOT_TOKEN"] = original


def test_configured_channels():
    os.environ["TELEGRAM_BOT_TOKEN"] = "tok"
    os.environ["MATRIX_ACCESS_TOKEN"] = "mat-tok"
    try:
        channels = configured_channels()
        assert "telegram" in channels
        assert "matrix" in channels
        assert "discord" not in channels
    finally:
        del os.environ["TELEGRAM_BOT_TOKEN"]
        del os.environ["MATRIX_ACCESS_TOKEN"]


def test_all_channel_names():
    names = all_channel_names()
    assert "telegram" in names
    assert "discord" in names
    assert "slack" in names
    assert "matrix" in names
    assert "irc" in names
    assert len(names) == len(set(names))


def test_get_channel_config_no_env():
    cfg = get_channel_config("nonexistent")
    assert cfg == {}
