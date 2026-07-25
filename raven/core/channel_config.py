from __future__ import annotations

import os
from typing import Any

# Maps channel name → { env_var: field_name }
# Legacy env var names for backward compat
_LEGACY_ENV: dict[str, dict[str, str]] = {
    "telegram": {"TELEGRAM_BOT_TOKEN": "bot_token"},
    "discord": {"DISCORD_BOT_TOKEN": "bot_token"},
    "slack": {"SLACK_BOT_TOKEN": "bot_token", "SLACK_SIGNING_SECRET": "signing_secret"},
    "matrix": {"MATRIX_ACCESS_TOKEN": "access_token", "MATRIX_HOMESERVER": "homeserver"},
    "whatsapp": {"WHATSAPP_TOKEN": "token", "WHATSAPP_PHONE_ID": "phone_id"},
    "googlechat": {"GOOGLECHAT_WEBHOOK_URL": "webhook_url"},
    "signal": {"SIGNAL_API_URL": "api_url"},
    "irc": {
        "IRC_SERVER": "server",
        "IRC_PORT": "port",
        "IRC_NICK": "nick",
        "IRC_PASSWORD": "password",
        "IRC_CHANNELS": "channels",
    },
    "teams": {"TEAMS_WEBHOOK_URL": "webhook_url"},
    "feishu": {"FEISHU_WEBHOOK_URL": "webhook_url", "FEISHU_APP_ID": "app_id", "FEISHU_APP_SECRET": "app_secret"},
    "line": {"LINE_CHANNEL_TOKEN": "channel_token", "LINE_CHANNEL_SECRET": "channel_secret"},
}

# Prefix-based config for channels added at runtime
_CHANNEL_FIELDS: dict[str, dict[str, str]] = {}


def register_channel_fields(name: str, field_map: dict[str, str]) -> None:
    _CHANNEL_FIELDS[name] = field_map


def get_channel_config(name: str) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    for var, field in _LEGACY_ENV.get(name, {}).items():
        val = os.environ.get(var)
        if val:
            cfg[field] = val
    for field, var in _CHANNEL_FIELDS.get(name, {}).items():
        val = os.environ.get(var)
        if val:
            cfg[field] = val
    return cfg


def has_any_channel(name: str) -> bool:
    for var in _LEGACY_ENV.get(name, {}):
        if os.environ.get(var):
            return True
    return any(os.environ.get(var) for var in _CHANNEL_FIELDS.get(name, {}).values())


def configured_channels() -> list[str]:
    seen: set[str] = set()
    for name in _LEGACY_ENV:
        if has_any_channel(name):
            seen.add(name)
    for name in _CHANNEL_FIELDS:
        if name not in _LEGACY_ENV and has_any_channel(name):
            seen.add(name)
    return sorted(seen)


def all_channel_names() -> list[str]:
    seen: set[str] = set(_LEGACY_ENV.keys())
    seen.update(_CHANNEL_FIELDS.keys())
    return sorted(seen)
