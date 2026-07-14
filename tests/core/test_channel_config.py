from __future__ import annotations

from raven.core.channel_config import (
    all_channel_names,
    configured_channels,
    get_channel_config,
    has_any_channel,
)


def test_get_channel_config_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    cfg = get_channel_config("telegram")
    assert cfg.get("bot_token") == "tok123"


def test_get_channel_config_slack(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-abc")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret456")
    cfg = get_channel_config("slack")
    assert cfg.get("bot_token") == "xoxb-abc"
    assert cfg.get("signing_secret") == "secret456"


def test_get_channel_config_irc(monkeypatch):
    monkeypatch.setenv("IRC_SERVER", "irc.libera.chat")
    monkeypatch.setenv("IRC_PORT", "6667")
    monkeypatch.setenv("IRC_NICK", "raven-bot")
    monkeypatch.setenv("IRC_PASSWORD", "hunter2")
    monkeypatch.setenv("IRC_CHANNELS", "#raven,#test")
    cfg = get_channel_config("irc")
    assert cfg.get("server") == "irc.libera.chat"
    assert cfg.get("port") == "6667"
    assert cfg.get("nick") == "raven-bot"
    assert cfg.get("password") == "hunter2"
    assert cfg.get("channels") == "#raven,#test"


def test_has_any_channel_true(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-tok")
    assert has_any_channel("discord") is True


def test_has_any_channel_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert has_any_channel("telegram") is False


def test_configured_channels(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "mat-tok")
    channels = configured_channels()
    assert "telegram" in channels
    assert "matrix" in channels
    assert "discord" not in channels


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
