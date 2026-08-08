from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from raven.core.config_discovery import auto_select_model
from raven.core.watermark import honeytoken_warning, is_honeytoken


class SafeSecretStr(SecretStr):
    """SecretStr that is falsy when the secret value is empty."""

    def __bool__(self) -> bool:
        return bool(self.get_secret_value())


_DEFAULT_TOOLS_DENY = (
    "group:automation",
    "group:runtime",
    "sessions.sessions_spawn",
    "api.http_post",
    "process.kill",
    "process.run",
    "process.run_python",
    "git.git_push",
    "git.git_pull",
)


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    openrouter_api_key: SafeSecretStr = SafeSecretStr("")
    anthropic_api_key: SafeSecretStr = SafeSecretStr("")
    openai_api_key: SafeSecretStr = SafeSecretStr("")
    groq_api_key: SafeSecretStr = SafeSecretStr("")
    ollama_base_url: str = "http://localhost:11434"  # default Ollama URL
    vllm_base_url: str = ""
    default_model: str = ""  # auto-discovered if empty
    model_fast: str = ""
    model_balanced: str = ""
    model_quality: str = ""
    critical_model: str = ""  # model used by the Truthful Orchestrator (falls back to default_model)
    critical_provider: str = ""  # dedicated provider key for critical calls (e.g. "openrouter")
    critical_api_key: SafeSecretStr = SafeSecretStr("")  # API key for the dedicated critical provider

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
    web_secret_key: SafeSecretStr = SafeSecretStr("")
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
    agent_token_timeout: float = 30.0
    agent_tool_timeout: float = 120.0
    workspace_path: str = ""
    channel_allow_from: str = ""
    mcp_servers: str = ""
    channel_sandbox_policy: str = ""
    """JSON mapping channel_id to sandbox policy name, e.g. {"telegram":"non-main","discord":"code-exec"}"""

    # --- Search Integration ---
    brave_search_api_key: SafeSecretStr = SafeSecretStr("")
    perplexity_api_key: SafeSecretStr = SafeSecretStr("")
    google_search_api_key: SafeSecretStr = SafeSecretStr("")
    google_cse_id: str = ""
    bing_search_api_key: SafeSecretStr = SafeSecretStr("")
    tavily_search_api_key: SafeSecretStr = SafeSecretStr("")

    # --- GitHub Integration ---
    github_token: SafeSecretStr = SafeSecretStr("")

    # --- CI/CD Integration ---
    gitlab_token: SafeSecretStr = SafeSecretStr("")
    gitlab_url: str = "https://gitlab.com"
    gitlab_webhook_secret: SafeSecretStr = SafeSecretStr("")
    jenkins_url: str = ""
    jenkins_user: str = ""
    jenkins_token: SafeSecretStr = SafeSecretStr("")

    # --- Media Generation ---
    replicate_api_token: SafeSecretStr = SafeSecretStr("")

    # --- OAuth / SSO ---
    oauth_redirect_base: str = "http://localhost:5173"
    oauth_google_client_id: SafeSecretStr = SafeSecretStr("")
    oauth_google_client_secret: SafeSecretStr = SafeSecretStr("")
    oauth_github_client_id: SafeSecretStr = SafeSecretStr("")
    oauth_github_client_secret: SafeSecretStr = SafeSecretStr("")
    oauth_microsoft_client_id: SafeSecretStr = SafeSecretStr("")
    oauth_microsoft_client_secret: SafeSecretStr = SafeSecretStr("")

    # --- Security Policy ---
    tools_profile: str = "messaging"
    tools_deny: str = ",".join(_DEFAULT_TOOLS_DENY)
    tools_allow: str = ""
    exec_security: str = "deny"
    exec_ask_mode: str = "always"
    workspace_only: bool = True
    context_visibility: str = "allowlist"
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

    token_budget_per_hour: int = 500_000
    """Max tokens (input + output) allowed per hour per user_id."""
    ghost_mode: bool = False

    def model_post_init(self, __context: Any) -> None:
        if not self.default_model:
            self.default_model = auto_select_model()
            logger.info("Auto-selected model: {}", self.default_model)
        if not self.web_secret_key:
            import secrets
            self.web_secret_key = SafeSecretStr(secrets.token_hex(32))
            logger.info("Auto-generated WEB_SECRET_KEY")

    metrics_port: int = 9090
    otlp_endpoint: str = ""
    redis_url: str = ""

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
    def resolved_data_dir(self) -> Path:
        return self.resolved_db_path.parent

    @property
    def resolved_log_file(self) -> Path:
        p = Path(self.log_file)
        if not p.is_absolute():
            base = Path(__file__).parent.parent.parent
            return base / p
        return p

    def validate_settings(self) -> bool:
        errors = []
        if not self.web_secret_key or self.web_secret_key.get_secret_value() == "change-me-in-production":
            errors.append("WEB_SECRET_KEY must be set to a non-default value")
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
    "groq_api_key": "GROQ_API_KEY",
}
for _attr, _env_name in _honeytoken_keys.items():
    _val = getattr(settings, _attr, SafeSecretStr(""))
    if _val and is_honeytoken(_env_name, _val.get_secret_value()):
        logger.warning(honeytoken_warning(_env_name))

if settings.web_secret_key.get_secret_value() in ("", "change-me-in-production"):
    logger.warning(
        "WEB_SECRET_KEY is default or empty — set a random key in .env for auth. "
        "Generate: python3 -c 'import secrets; print(secrets.token_hex(32))'"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return settings


def apply_ghost_mode(overrides: dict[str, Any] | None = None) -> None:
    s = get_settings()
    s.ghost_mode = True
    s.default_model = "ollama/llama3"
    if overrides:
        for k, v in overrides.items():
            if hasattr(s, k):
                setattr(s, k, v)
    logger.info("Ghost mode activated — LLM: {}, voice: local-only", s.default_model)
