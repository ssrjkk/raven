from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".raven"
CONFIG_FILE = CONFIG_DIR / "config.json"


DEFAULTS: dict[str, Any] = {
    "openrouter_api_key": "",
    "anthropic_api_key": "",
    "openai_api_key": "",
    "ollama_base_url": "",
    "default_model": "openrouter/google/gemini-2.0-flash-001",
    "telegram_bot_token": "",
    "discord_bot_token": "",
    "slack_bot_token": "",
    "web_port": 18888,
    "web_secret_key": "",
    "web_cors_origins": "*",
    "dm_policy": "pairing",
    "rate_limit_max": 60,
    "json_log": True,
    "log_level": "INFO",
    "db_path": "data/raven.db",
    "llm_retry_max": 3,
    "pairing_code_length": 6,
}


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self._path = path or CONFIG_FILE
        self._data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if self._path.exists():
            raw = self._path.read_text(encoding="utf-8")
            if raw.strip():
                try:
                    self._data = json.loads(raw)
                except json.JSONDecodeError:
                    self._data = {}
        for key, val in DEFAULTS.items():
            self._data.setdefault(key, val)
        return self._data

    def save(self, data: dict[str, Any] | None = None) -> None:
        if data is not None:
            self._data.update(data)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str),
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    @property
    def path(self) -> Path:
        return self._path

    def apply_to_env(self) -> None:
        mapping = {
            "openrouter_api_key": "OPENROUTER_API_KEY",
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
            "ollama_base_url": "OLLAMA_BASE_URL",
            "default_model": "DEFAULT_MODEL",
            "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
            "discord_bot_token": "DISCORD_BOT_TOKEN",
            "slack_bot_token": "SLACK_BOT_TOKEN",
            "web_port": "WEB_PORT",
            "web_secret_key": "WEB_SECRET_KEY",
            "web_cors_origins": "WEB_CORS_ORIGINS",
            "dm_policy": "DM_POLICY",
            "rate_limit_max": "RATE_LIMIT_MAX",
            "json_log": "JSON_LOG",
            "log_level": "LOG_LEVEL",
            "db_path": "DB_PATH",
            "llm_retry_max": "LLM_RETRY_MAX",
            "pairing_code_length": "PAIRING_CODE_LENGTH",
        }
        for cfg_key, env_key in mapping.items():
            val = self._data.get(cfg_key)
            if val is not None:
                os.environ[env_key] = str(val)


config_store = ConfigStore()
