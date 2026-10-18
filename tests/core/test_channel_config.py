from __future__ import annotations

from pathlib import Path

import raven.channels
from raven.core.channel_config import (
    all_channel_names,
    configured_channels,
    get_channel_config,
    has_any_channel,
)

_GATEWAY_RUNNER = Path(raven.channels.__file__).parent.parent / "cli" / "gateway_runner.py"


def _channel_packages() -> set[str]:
    return {p.parent.name for p in Path(raven.channels.__file__).parent.glob("*/channel.py")}


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
    assert "email" in names
    assert len(names) == len(set(names))


def test_get_channel_config_no_env():
    cfg = get_channel_config("nonexistent")
    assert cfg == {}


def test_every_channel_package_is_wired_into_the_gateway():
    source = _GATEWAY_RUNNER.read_text(encoding="utf-8")
    unwired = {name for name in _channel_packages() if f'("{name}", ' not in source}
    assert not unwired


def test_every_wired_channel_is_discoverable_by_doctor():
    # webchat is served by the gateway itself and needs no platform credentials.
    missing = _channel_packages() - set(all_channel_names()) - {"webchat"}
    assert not missing


def test_email_env_map_reaches_the_channel(monkeypatch):
    for var in (
        "EMAIL_SMTP_HOST",
        "EMAIL_SMTP_PORT",
        "EMAIL_SMTP_USER",
        "EMAIL_SMTP_PASS",
        "EMAIL_IMAP_HOST",
        "EMAIL_IMAP_PORT",
        "EMAIL_IMAP_USER",
        "EMAIL_IMAP_PASS",
        "EMAIL_INBOX_FOLDER",
        "EMAIL_POLL_INTERVAL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    assert has_any_channel("email") is True
    assert get_channel_config("email") == {"smtp_host": "smtp.example.com", "imap_host": "imap.example.com"}
    assert "email" in configured_channels()
