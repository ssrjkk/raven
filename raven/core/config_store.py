from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from raven.core._json import json

CONFIG_DIR = Path.home() / ".raven"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _defaults_from_settings() -> dict[str, Any]:
    from raven.core.config import Settings
    s = Settings()
    return {
        "openrouter_api_key": s.openrouter_api_key,
        "anthropic_api_key": s.anthropic_api_key,
        "openai_api_key": s.openai_api_key,
        "ollama_base_url": s.ollama_base_url,
        "default_model": s.default_model,

        "web_port": s.web_port,
        "web_secret_key": s.web_secret_key,
        "web_cors_origins": s.web_cors_origins,
        "dm_policy": s.dm_policy,
        "rate_limit_max": s.rate_limit_max,
        "json_log": s.json_log,
        "log_level": s.log_level,
        "db_path": s.db_path,
        "llm_retry_max": s.llm_retry_max,
    }


DEFAULTS: dict[str, Any] = _defaults_from_settings()


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
            if val is not None and env_key not in os.environ:
                os.environ[env_key] = str(val)


config_store = ConfigStore()
