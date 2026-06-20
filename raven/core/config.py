from __future__ import annotations

from pathlib import Path

from loguru import logger
from pydantic_settings import BaseSettings

_DEFAULT_TOOLS_DENY = [
    "group:automation",
    "group:runtime",
    "sessions_spawn",
    "shell.exec",
    "browser.control",
]


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "ollama/llama3"

    telegram_bot_token: str = ""
    discord_bot_token: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    matrix_homeserver: str = ""
    matrix_access_token: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    googlechat_webhook_url: str = ""
    signal_api_url: str = ""
    irc_server: str = ""
    irc_port: int = 6697
    irc_nick: str = ""
    irc_password: str = ""
    irc_channels: str = ""
    teams_webhook_url: str = ""
    feishu_webhook_url: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    line_channel_token: str = ""
    line_channel_secret: str = ""

    dm_policy: str = "pairing"
    web_port: int = 18888
    web_secret_key: str = ""
    web_cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:18888"
    rate_limit_max: int = 60
    rate_limit_window: int = 60
    json_log: bool = True
    log_level: str = "INFO"
    db_path: str = "data/raven.db"
    log_file: str = "data/raven.log"
    llm_timeout: int = 120
    llm_retry_max: int = 3
    llm_retry_delay: float = 1.0
    workspace_path: str = ""
    channel_allow_from: str = ""

    # --- Security Policy ---
    tools_profile: str = "messaging"
    tools_deny: str = ",".join(_DEFAULT_TOOLS_DENY)
    tools_allow: str = ""
    exec_security: str = "deny"
    exec_ask_mode: str = "always"
    workspace_only: bool = True
    context_visibility: str = "all"
    sandbox_mode: str = "non-main"
    sandbox_backend: str = "subprocess"

    @property
    def resolved_workspace(self) -> Path | None:
        if not self.workspace_path:
            return None
        p = Path(self.workspace_path)
        if not p.is_absolute():
            base = Path(__file__).parent.parent.parent
            return base / p
        return p

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

    def validate(self) -> bool:  # type: ignore[override]
        errors = []
        if not self.web_secret_key:
            errors.append("WEB_SECRET_KEY must be set to a non-empty value")
        if self.dm_policy not in ("pairing", "open", "closed"):
            errors.append(f"DM_POLICY must be 'pairing', 'open', or 'closed', got '{self.dm_policy}'")
        if self.web_port < 1 or self.web_port > 65535:
            errors.append(f"WEB_PORT must be 1-65535, got {self.web_port}")
        if self.rate_limit_max < 1:
            errors.append(f"RATE_LIMIT_MAX must be >= 1, got {self.rate_limit_max}")
        if self.llm_retry_max < 0:
            errors.append(f"LLM_RETRY_MAX must be >= 0, got {self.llm_retry_max}")
        if errors:
            for err in errors:
                logger.error("Config validation error: {}", err)
            raise ValueError("\n".join(errors))
        return True


settings = Settings()
