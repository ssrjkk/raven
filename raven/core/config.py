from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic_settings import BaseSettings

from raven.core.watermark import honeytoken_warning, is_honeytoken

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
    ollama_base_url: str = "http://localhost:11434"  # default Ollama URL
    vllm_base_url: str = ""
    default_model: str = "ollama/llama3"

    # --- Tier / rate limits ---
    tier_default: str = "free"
    tier_free_rpd: int = 50
    tier_free_rpm: int = 20
    tier_free_concurrent: int = 1
    tier_pro_rpd: int = 10_000
    tier_pro_rpm: int = 100
    tier_pro_concurrent: int = 5

    dm_policy: str = "pairing"
    web_port: int = 18888
    ravenflow_port: int = 18789
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
    mcp_servers: str = ""
    channel_sandbox_policy: str = ""
    """JSON mapping channel_id to sandbox policy name, e.g. {"telegram":"non-main","discord":"code-exec"}"""

    # --- Search Integration ---
    brave_search_api_key: str = ""
    perplexity_api_key: str = ""
    google_search_api_key: str = ""
    google_cse_id: str = ""
    bing_search_api_key: str = ""
    tavily_search_api_key: str = ""

    # --- GitHub Integration ---
    github_token: str = ""

    # --- CI/CD Integration ---
    gitlab_token: str = ""
    gitlab_url: str = "https://gitlab.com"
    gitlab_webhook_secret: str = ""
    jenkins_url: str = ""
    jenkins_user: str = ""
    jenkins_token: str = ""

    # --- Media Generation ---
    replicate_api_token: str = ""

    # --- OAuth / SSO ---
    oauth_redirect_base: str = "http://localhost:5173"
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_github_client_id: str = ""
    oauth_github_client_secret: str = ""
    oauth_microsoft_client_id: str = ""
    oauth_microsoft_client_secret: str = ""

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

    # --- Context Window ---
    context_window_enabled: bool = True
    context_window_max_tokens: int = 128000
    context_window_warning_threshold: float = 0.8
    context_window_summarization_threshold: float = 0.9
    context_window_hard_limit: float = 0.95
    context_window_reserved_tokens: int = 2000
    context_window_sliding_size: int = 20

    ghost_mode: bool = False

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

    def validate_settings(self) -> bool:
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

# ── Honeytoken watermark check ────────────────────────────────
_honeytoken_keys = {
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}
for _attr, _env_name in _honeytoken_keys.items():
    _val = getattr(settings, _attr, "")
    if _val and is_honeytoken(_env_name, _val):
        logger.warning(honeytoken_warning(_env_name))

if settings.web_secret_key in ("", "change-me-in-production"):
    logger.warning(
        "WEB_SECRET_KEY is default or empty — set a random key in .env for auth. "
        "Generate: python3 -c 'import secrets; print(secrets.token_hex(32))'"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def apply_ghost_mode(overrides: dict[str, Any] | None = None) -> None:
    s = get_settings()
    s.ghost_mode = True
    s.default_model = "ollama/llama3"
    if overrides:
        for k, v in overrides.items():
            if hasattr(s, k):
                setattr(s, k, v)
    logger.info("Ghost mode activated — LLM: {}, voice: local-only", s.default_model)
