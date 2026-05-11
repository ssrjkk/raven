from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = ""
    default_model: str = "openrouter/openai/gpt-4o"

    telegram_bot_token: str = ""
    discord_bot_token: str = ""

    dm_policy: str = "pairing"
    web_port: int = 18888
    web_secret_key: str = ""

    log_level: str = "INFO"
    db_path: str = "data/raven.db"
    log_file: str = "data/raven.log"

    @property
    def resolved_db_path(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            base = Path(__file__).parent.parent.parent
            return base / p
        return p

    @property
    def resolved_log_file(self) -> Path:
        p = Path(self.log_file)
        if not p.is_absolute():
            base = Path(__file__).parent.parent.parent
            return base / p
        return p


settings = Settings()
