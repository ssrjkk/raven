from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from loguru import logger
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings

from raven.core.config_discovery import auto_select_model
from raven.core.watermark import honeytoken_warning, is_honeytoken


class SafeSecretStr(SecretStr):
    """SecretStr that is falsy when the secret value is empty."""

    def __bool__(self) -> bool:
        return bool(self.get_secret_value())


_DEFAULT_TOOLS_DENY = (
    # group:automation (workflow + CI)
    "ci_jenkins_job",
    "ci_jenkins_status",
    "ci_list_runs",
    "ci_list_workflows",
    "ci_pipeline_status",
    "ci_run_workflow",
    "ci_trigger_pipeline",
    "workflow_get_template",
    "workflow_instantiate",
    "workflow_list_categories",
    "workflow_list_templates",
    "workflow_schedule",
    # group:runtime (system)
    "dream_cycle",
    "dream_status",
    "env_get",
    "env_list",
    "nodes_exec",
    "nodes_list",
    "nodes_register",
    "nodes_unregister",
    "process_kill",
    "process_list",
    "python",
    "shell",
    "sessions.sessions_spawn",
    "api.http_post",
    "process.kill",
    "process.run",
    "process.run_python",
    "git.git_push",
    "git.git_pull",
)


# Env-file cascade: project-local .env wins, then the user-global ~/.raven/.env,
# then the .env next to the raven installation (editable installs). This makes
# the CLI/agent work from any working directory, not just the repo root.
# NOTE: pydantic-settings gives later files higher precedence, so the list is
# ordered lowest-priority first.
_RAVEN_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE_CANDIDATES: list[str] = [
    str(_RAVEN_ROOT / ".env"),
    str(Path.home() / ".raven" / ".env"),
    ".env",
]


class Settings(BaseSettings):
    model_config = {
        "env_file": _ENV_FILE_CANDIDATES,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    openrouter_api_key: SafeSecretStr = SafeSecretStr("")
    anthropic_api_key: SafeSecretStr = SafeSecretStr("")
    openai_api_key: SafeSecretStr = SafeSecretStr("")
    groq_api_key: SafeSecretStr = SafeSecretStr("")
    ollama_base_url: str = "http://localhost:11434"  # default Ollama URL
    vllm_base_url: str = ""
    llm_local_base_model: str = ""
    llm_local_adapter_path: str = ""
    llm_local_max_new_tokens: int = 256
    llm_local_revision: str = "main"
    """Hugging Face revision the local provider downloads. A commit id, not a branch, is what makes a load reproducible."""
    default_model: str = ""  # auto-discovered if empty
    model_fast: str = ""
    model_balanced: str = ""
    model_quality: str = ""
    # Truthful Orchestrator (Chain-of-Verification). The documented
    # RAVEN_CRITICAL_* spelling is accepted as an alias of CRITICAL_*.
    critical_model: str = Field(
        default="",
        validation_alias=AliasChoices("critical_model", "RAVEN_CRITICAL_MODEL"),
    )  # model used by the Truthful Orchestrator (falls back to default_model)
    critical_provider: str = Field(
        default="",
        validation_alias=AliasChoices("critical_provider", "RAVEN_CRITICAL_PROVIDER"),
    )  # dedicated provider key for critical calls (e.g. "openrouter")
    critical_api_key: SafeSecretStr = Field(
        default=SafeSecretStr(""),
        validation_alias=AliasChoices("critical_api_key", "RAVEN_CRITICAL_API_KEY"),
    )  # API key for the dedicated critical provider

    dm_policy: str = "pairing"
    web_port: int = 18888
    web_host: str = "127.0.0.1"
    """Bind address for the web API. Use 0.0.0.0 only when a firewall/reverse proxy guards it."""
    ravenflow_port: int = 18789
    ravenflow_host: str = "127.0.0.1"
    """Bind address for the RavenFlow gateway. Use 0.0.0.0 only when a firewall/reverse proxy guards it."""
    web_secret_key: SafeSecretStr = SafeSecretStr("")
    web_cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:18888"
    web_cors_allow_credentials: bool = True
    """Credentialed cross-origin requests. Keep on for the SPA; with it on, `*` is refused below."""
    rate_limit_max: int = 60
    rate_limit_window: int = 60
    trust_forwarded_for: bool = False
    """Honour `X-Forwarded-For` from a peer that is not a proxy we installed.

    Set it when a cloud load balancer or an off-host reverse proxy terminates the connection; leaving it
    off means a caller can choose the address the rate limiter and the login lockout attribute it to.
    Loopback and private-range peers are honoured either way, which is what the shipped compose stack
    needs.
    """
    json_log: bool = True
    log_level: str = "INFO"
    db_path: str = "data/raven.db"
    log_file: str = "data/raven.log"
    llm_timeout: int = 120
    llm_retry_max: int = 3
    llm_retry_delay: float = 1.0
    llm_max_concurrent: int = 10
    llm_queue_timeout: float = 5.0
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
    """Execution backend for code tools: ``subprocess``, ``docker`` or ``none`` (in-process)."""

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

    # --- Channel send resilience (bulkhead + circuit breaker) ---
    channel_send_concurrency: int = 4
    """Max concurrent in-flight sends per channel (bulkhead isolation)."""
    channel_send_timeout: float = 30.0
    """Per-send timeout in seconds — a hung channel send must not stall the loop."""
    channel_send_failure_threshold: int = 5
    """Consecutive send failures before the per-channel circuit opens."""
    channel_send_recovery_timeout: float = 30.0
    """Seconds the per-channel circuit stays open before probing (half-open)."""

    # --- Plugin registry / marketplace ---
    plugin_registry_url: str = ""
    """Base URL or directory of the plugin catalog used by `raven plugins update`."""

    def model_post_init(self, __context: Any) -> None:
        if not self.default_model:
            self.default_model = auto_select_model()
            logger.info("Auto-selected model: {}", self.default_model)
        if not self.web_secret_key:
            import secrets

            key_file = self.resolved_data_dir / "web_secret_key"
            stored: str | None = None
            try:
                if key_file.is_file():
                    candidate = key_file.read_text(encoding="utf-8").strip()
                    if candidate:
                        stored = candidate
            except OSError as exc:
                logger.warning("Failed to read WEB_SECRET_KEY file {}: {}", key_file, exc)
            if stored:
                self.web_secret_key = SafeSecretStr(stored)
                logger.info("Loaded WEB_SECRET_KEY from {}", key_file)
                with contextlib.suppress(OSError):
                    key_file.chmod(0o600)
            else:
                self.web_secret_key = SafeSecretStr(secrets.token_hex(32))
                logger.info("Auto-generated WEB_SECRET_KEY")
                try:
                    key_file.parent.mkdir(parents=True, exist_ok=True)
                    key_file.write_text(self.web_secret_key.get_secret_value(), encoding="utf-8")
                    with contextlib.suppress(OSError):
                        key_file.chmod(0o600)
                    logger.info("Persisted WEB_SECRET_KEY to {}", key_file)
                except OSError as exc:
                    logger.warning("Failed to persist WEB_SECRET_KEY to {}: {}", key_file, exc)
        self._check_cors_policy()

    def _check_cors_policy(self) -> None:
        """Refuse a CORS configuration that cannot mean what it says.

        With credentials on, Starlette answers a wildcard with the caller's own Origin, so `*` does
        not mean "nobody" -- it means "any site may read a logged-in user's responses". A wildcard
        subdomain is a different failure: it is matched literally, so it silently matches nothing.
        """
        origins = self.cors_origin_list
        if self.web_cors_allow_credentials and any(origin.strip() == "*" for origin in origins):
            raise ValueError(
                "WEB_CORS_ORIGINS=* with WEB_CORS_ALLOW_CREDENTIALS=on lets any origin read "
                "authenticated responses; list the origins you serve, or set "
                "WEB_CORS_ALLOW_CREDENTIALS=off for a public API"
            )
        for origin in origins:
            if origin == "*":
                continue
            parts = urlsplit(origin)
            if parts.scheme in ("http", "https") and parts.netloc and "*" not in origin:
                continue
            raise ValueError(
                f"WEB_CORS_ORIGINS entry {origin!r} is not usable: a wildcard subdomain is matched "
                "literally and matches nothing; give scheme://host[:port], or '*' alone with "
                "WEB_CORS_ALLOW_CREDENTIALS=off"
            )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.web_cors_origins.split(",") if origin.strip()]

    metrics_port: int = 9090
    otlp_endpoint: str = ""
    redis_url: str = ""

    @property
    def resolved_workspace(self) -> Path | None:
        if not self.workspace_path:
            return None
        p = Path(self.workspace_path).expanduser()
        return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()

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
        if self.sandbox_backend not in ("subprocess", "docker", "none"):
            errors.append(f"SANDBOX_BACKEND must be 'subprocess', 'docker', or 'none', got '{self.sandbox_backend}'")
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


def sanitize_no_proxy_env() -> None:
    """Rewrite the no-proxy lists so one bracketed IPv6 entry cannot break every client in the process.

    httpx turns each NO_PROXY entry into a URL pattern, and the pattern ``all://[::1]`` reads ``:1]``
    as a port and raises ``InvalidURL`` inside ``httpx.Client()`` — so a machine-level
    ``NO_PROXY=localhost,[::1]`` fails every provider call before a request is sent. Brackets are the
    URL form of an IPv6 literal, not the list form, so dropping them bypasses the same hosts.
    """
    for name in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(name)
        if raw is None:
            continue
        entries: list[str] = []
        for entry in raw.split(","):
            host = entry.strip().strip("[]")
            if host and host not in entries:
                entries.append(host)
        os.environ[name] = ",".join(entries)


sanitize_no_proxy_env()

settings = Settings()

if settings.web_secret_key.get_secret_value() in ("", "change-me-in-production"):
    logger.warning(
        "WEB_SECRET_KEY is default or empty — set a random key in .env for auth. "
        "Generate: python3 -c 'import secrets; print(secrets.token_hex(32))'"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return settings


def data_path(*parts: str) -> Path:
    """Runtime artifacts live under the configured data dir, never the cwd."""
    return settings.resolved_data_dir.joinpath(*parts)


def _ghost_fallback_model(base_url: str) -> str:
    """A model Ollama actually serves, preferring the bundled free one, for a hosted name in ghost mode."""
    from raven.core.heretic_model import is_bundled_model, list_ollama_models

    try:
        names = list_ollama_models(base_url, timeout=3.0)
    except Exception:
        names = []
    for name in names:
        if is_bundled_model(f"ollama/{name}"):
            return f"ollama/{name}"
    if names:
        return f"ollama/{names[0]}"
    logger.warning("Ghost mode: Ollama at {} serves nothing to fall back to; keeping ollama/llama3", base_url)
    return "ollama/llama3"


def apply_ghost_mode(overrides: dict[str, Any] | None = None) -> None:
    """Ghost mode means no external API call, not "forget the model the operator configured".

    The router routes every ghost-mode call to Ollama, so an ``ollama/`` model — the bundled free one
    included — is kept exactly as configured. Only a hosted name has to be replaced, and then with
    something the local runtime answers to instead of a hardcoded guess that was never pulled.
    """
    s = get_settings()
    s.ghost_mode = True
    if not s.default_model.startswith("ollama/"):
        s.default_model = _ghost_fallback_model(s.ollama_base_url)
    if overrides:
        for k, v in overrides.items():
            if hasattr(s, k):
                setattr(s, k, v)
    logger.info("Ghost mode activated — LLM: {}, voice: local-only", s.default_model)


_USER_ENV_FILE = Path.home() / ".raven" / ".env"

_TRUE_WORDS = ("true", "1", "yes", "on")
_FALSE_WORDS = ("false", "0", "no", "off")


@dataclass(frozen=True)
class RuntimeSwitch:
    """What one environment name does to a running gateway.

    ``env_name`` is where the value lives, ``attr`` the ``Settings`` field it owns, ``kind`` how a raw
    string becomes that field's type, ``rebind`` what has to be rebuilt because a consumer cached the
    old value, and ``restart_required`` the honest answer for anything whose consumer bound the value at
    startup: uvicorn has the port, so writing it changes the next process, not this one.
    """

    attr: str
    env_name: str
    kind: Literal["str", "int", "bool", "secret"] = "str"
    choices: Callable[[], tuple[str, ...]] = lambda: ()
    minimum: int | None = None
    maximum: int | None = None
    restart_required: bool = False
    rebind: tuple[Callable[[], None], ...] = ()


def _dm_policy_choices() -> tuple[str, ...]:
    """The policies the gateway can actually act on — the same set ``validate_settings`` refuses without."""
    return ("pairing", "open", "closed")


def _visibility_choices() -> tuple[str, ...]:
    from raven.core.security.context_filter import ContextVisibility

    return tuple(str(value) for value in ContextVisibility)


def _log_level_choices() -> tuple[str, ...]:
    """The level names both sinks accept, probed rather than listed.

    loguru raises for a name it does not know and structlog falls back to INFO for anything the stdlib
    does not export, so the intersection is the real domain; the aliases the stdlib spells twice (WARN /
    WARNING, FATAL / CRITICAL) collapse onto the one spelling both sinks honour.

    The probe reads the constants the stdlib module exports, not ``getLevelNamesMapping()``: that
    mapping is a process-global registry any imported library can extend — uvicorn writes ``TRACE = 5``
    into it at import — so a domain read from it would let the console accept ``LOG_LEVEL=TRACE`` only in
    a process that had already imported uvicorn, and the same `.env` would be refused in another.
    """
    import logging

    from loguru import logger

    by_value: dict[int, str] = {}
    exported = (
        (name, value)
        for name, value in sorted(vars(logging).items())
        if isinstance(value, int) and not isinstance(value, bool) and name.isupper()
    )
    for name, value in exported:
        try:
            logger.level(name)
        except ValueError:
            continue
        by_value.setdefault(value, name)
    return tuple(by_value[value] for value in sorted(by_value))


def _rebind_rate_limiter() -> None:
    """Rebuild the per-IP limiter: the middleware holds one instance for the life of the process."""
    from raven.core import middleware

    middleware.rate_limiter = middleware.build_rate_limiter()


def _rebind_logging() -> None:
    """Re-open the sinks: loguru keeps the level and the line shape of every handler from setup time."""
    from raven.core.logging import setup_logging

    setup_logging()


# Every switch the console, the CLI and the `.env` watcher can move under a live gateway. The admin
# screen used to write its keys into `~/.raven/config.json` and answer `{"ok": true}` — a file no
# running process ever read — so one table now owns both the name space and the effect.
_RUNTIME_SWITCHES: dict[str, RuntimeSwitch] = {
    switch.attr: switch
    for switch in (
        RuntimeSwitch("default_model", "DEFAULT_MODEL"),
        RuntimeSwitch("model_fast", "MODEL_FAST"),
        RuntimeSwitch("model_balanced", "MODEL_BALANCED"),
        RuntimeSwitch("model_quality", "MODEL_QUALITY"),
        RuntimeSwitch("ollama_base_url", "OLLAMA_BASE_URL"),
        RuntimeSwitch("dm_policy", "DM_POLICY", choices=_dm_policy_choices),
        RuntimeSwitch("context_visibility", "CONTEXT_VISIBILITY", choices=_visibility_choices),
        RuntimeSwitch("rate_limit_max", "RATE_LIMIT_MAX", "int", minimum=1, rebind=(_rebind_rate_limiter,)),
        RuntimeSwitch("log_level", "LOG_LEVEL", choices=_log_level_choices, rebind=(_rebind_logging,)),
        RuntimeSwitch("json_log", "JSON_LOG", "bool", rebind=(_rebind_logging,)),
        RuntimeSwitch("web_port", "WEB_PORT", "int", minimum=1, maximum=65535, restart_required=True),
        RuntimeSwitch("openrouter_api_key", "OPENROUTER_API_KEY", "secret"),
        RuntimeSwitch("anthropic_api_key", "ANTHROPIC_API_KEY", "secret"),
        RuntimeSwitch("openai_api_key", "OPENAI_API_KEY", "secret"),
        RuntimeSwitch("groq_api_key", "GROQ_API_KEY", "secret"),
    )
}


def runtime_switch_keys() -> tuple[str, ...]:
    """The names a caller may write through the console, the CLI or the env file."""
    return tuple(_RUNTIME_SWITCHES)


def runtime_switches() -> tuple[RuntimeSwitch, ...]:
    """The table itself, in declaration order — what the documentation and drift gates walk."""
    return tuple(_RUNTIME_SWITCHES.values())


def console_config_keys() -> tuple[str, ...]:
    """The switches `GET /api/admin/config` answers: everything writable except the credentials."""
    return tuple(key for key, switch in _RUNTIME_SWITCHES.items() if switch.kind != "secret")


def coerce_runtime_switch(key: str, raw: str, *, require_key_shape: bool = True) -> tuple[Any, str]:
    """The typed value a switch takes and the text that persists for it, refusing what it cannot hold.

    The console used to store whatever string a caller sent, so ``RATE_LIMIT_MAX=0`` came back as a
    limiter that blocks every request and ``DM_POLICY=opn`` as a policy that is neither open nor closed.
    ``require_key_shape`` is only true for a human typing a credential: a gateway copying its own
    environment onto ``Settings`` must not refuse a working key because its prefix is unusual.
    """
    switch = _RUNTIME_SWITCHES[key]
    text = raw.strip()
    if not text:
        raise ValueError(f"{switch.env_name} must not be empty")
    if switch.kind == "int":
        try:
            number = int(text)
        except ValueError:
            raise ValueError(f"{switch.env_name} must be an integer, got {text!r}") from None
        if switch.minimum is not None and number < switch.minimum:
            raise ValueError(f"{switch.env_name} must be >= {switch.minimum}, got {number}")
        if switch.maximum is not None and number > switch.maximum:
            raise ValueError(f"{switch.env_name} must be <= {switch.maximum}, got {number}")
        return number, str(number)
    if switch.kind == "bool":
        lowered = text.lower()
        if lowered in _TRUE_WORDS:
            return True, "true"
        if lowered in _FALSE_WORDS:
            return False, "false"
        raise ValueError(f"{switch.env_name} must be true or false, got {text!r}")
    if switch.kind == "secret":
        # The prefix table lives with the discovery that reads it; a second copy here is how a switch
        # starts accepting a key the provider will not use.
        from raven.core.config_discovery import _KEY_PATTERNS, _validate_key

        if require_key_shape and not _validate_key(switch.env_name, text):
            expected = _KEY_PATTERNS.get(switch.env_name) or []
            shape = f"one of {', '.join(expected)}" if expected else "at least 16 characters"
            raise ValueError(f"{switch.env_name} does not look like a real key (expected {shape})")
        return SafeSecretStr(text), text
    domain = switch.choices()
    if domain and text not in domain:
        raise ValueError(f"{switch.env_name} must be one of {', '.join(domain)}, got {text!r}")
    return text, text


@dataclass(frozen=True)
class SwitchResult:
    """What writing a switch did, in the terms a caller can act on and a log can hold."""

    key: str
    env_name: str
    value: Any
    applied: bool
    restart_required: bool
    env_file: str
    warnings: tuple[str, ...] = ()
    secret: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "env_name": self.env_name,
            "applied": self.applied,
            "restart_required": self.restart_required,
            "env_file": self.env_file,
            "warnings": list(self.warnings),
        }
        if not self.secret:
            payload["value"] = self.value
        return payload


async def _forget_cached_provider(env_name: str) -> None:
    """Drop the provider built with the old credential, and re-read which keys the process now has.

    ``LLMRouter`` caches one client per provider, and the discovery table is cached too, so a rotated
    key would otherwise sit unused: the next call would keep signing with the old one, or report the
    provider as unavailable while its new value is already in the environment.
    """
    from raven.core.config_discovery import get_discovered_keys
    from raven.core.llm.router import PROVIDER_ENV_KEYS, default_llm_router

    provider = next((name for name, variable in PROVIDER_ENV_KEYS.items() if variable == env_name), "")
    if provider:
        await default_llm_router().invalidate_provider(provider)
    get_discovered_keys(force=True)


async def apply_runtime_switch(key: str, raw: str) -> SwitchResult:
    """Write one switch where a running gateway reads it, and say honestly what that changed.

    Reading the shadow and the previous value happens before the write: setting the switch also updates
    this process's environment, after which an export made outside the env files can no longer be told
    apart from the value just written.
    """
    switch = _RUNTIME_SWITCHES[key]
    value, text = coerce_runtime_switch(key, raw)
    shadow = overshadowing_env_value(switch.env_name)
    canary = switch.kind == "secret" and is_honeytoken(switch.env_name, text)
    env_file = effective_env_file()
    write_env_value(switch.env_name, text)
    applied = not switch.restart_required
    if applied:
        setattr(get_settings(), switch.attr, value)

    warnings: list[str] = []
    if shadow is not None and switch.kind != "secret" and shadow != text:
        warnings.append(
            f"{switch.env_name}={shadow!r} is exported outside the env files and beats {env_file} at "
            "next start — clear it there or the switch will not hold"
        )
    if canary:
        logger.warning(honeytoken_warning(switch.env_name))
        warnings.append(f"{switch.env_name} is a canary this build issued, not a real credential")
    if switch.restart_required:
        warnings.append(f"{switch.env_name} needs a restart: the running process already bound it")
    else:
        for hook in switch.rebind:
            try:
                hook()
            except Exception as exc:
                applied = False
                warnings.append(f"{switch.env_name} was stored but its consumer refused to rebind: {exc}")
        if switch.kind == "secret":
            try:
                await _forget_cached_provider(switch.env_name)
            except Exception as exc:
                applied = False
                warnings.append(f"{switch.env_name} was stored but the cached provider survived: {exc}")
    return SwitchResult(
        key=key,
        env_name=switch.env_name,
        value=value,
        applied=applied,
        restart_required=switch.restart_required,
        env_file=str(env_file),
        warnings=tuple(warnings),
        secret=switch.kind == "secret",
    )


def refresh_settings_from_env() -> list[str]:
    """Copy the runtime-switchable env names onto the live settings object and name what moved.

    ``Settings`` reads the environment once, at import, so editing ``DEFAULT_MODEL`` in ``.env`` used to
    change only the next process while the running gateway kept answering from the old model.
    ``ConfigWatcher`` keeps ``os.environ`` current and calls this. An empty value is skipped: an unset
    name must not wipe an auto-discovered model, and a value the switch cannot hold is named in the log
    and left alone rather than pushed into a typed field.
    """
    changed: list[str] = []
    hooks: list[Callable[[], None]] = []
    s = get_settings()
    for switch in _RUNTIME_SWITCHES.values():
        if switch.restart_required:
            continue
        raw = os.environ.get(switch.env_name, "").strip()
        if not raw:
            continue
        try:
            value, _ = coerce_runtime_switch(switch.attr, raw, require_key_shape=False)
        except ValueError as exc:
            logger.warning("[config] ignored the environment's {}: {}", switch.env_name, exc)
            continue
        if getattr(s, switch.attr, None) == value:
            continue
        setattr(s, switch.attr, value)
        changed.append(switch.env_name)
        hooks.extend(hook for hook in switch.rebind if hook not in hooks)
    for hook in hooks:
        hook()
    if changed:
        logger.info("[config] runtime switch applied: {}", ", ".join(changed))
    return changed


def env_file_candidates() -> list[Path]:
    """Every file :class:`Settings` reads, in ascending precedence — the last one wins.

    De-duplicated by real path: run from the install root, ``<root>/.env`` and ``./.env`` are the same
    file listed twice, and a reader that walks the tail of this list would report the file as shadowing
    itself.
    """
    paths: list[Path] = []
    seen: set[str] = set()
    for candidate in _ENV_FILE_CANDIDATES:
        path = Path(candidate)
        path = path if path.is_absolute() else Path.cwd() / path
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def effective_env_file() -> Path:
    """The env file a runtime switch has to write for :class:`Settings` to obey it.

    Precedence is decided by position in ``_ENV_FILE_CANDIDATES`` (pydantic-settings lets the later
    file win), so a value written to a lower-precedence file is silently overridden. The last existing
    candidate is therefore the only honest target; when none exists yet the user-level file is created,
    because unlike ``./.env`` it is found from every working directory.
    """
    for path in reversed(env_file_candidates()):
        if path.is_file():
            return path
    return _USER_ENV_FILE


def overshadowing_env_value(env_name: str) -> str | None:
    """A value for ``env_name`` that came from outside the env files and therefore outranks them.

    Measured on this install (2026-11-10): with ``DEFAULT_MODEL=file/model`` in ``./.env`` and
    ``DEFAULT_MODEL=shell/model`` in the process environment, ``Settings`` resolves ``shell/model`` —
    pydantic-settings applies the real environment after every dotenv file. A service unit, a Windows
    service environment or a shell profile that exports the name therefore keeps beating whatever a
    runtime switch writes, which is how a switch looks dead. None means the switch wins: the name is
    unset in the environment, or the environment already agrees with the file.
    """
    value = os.environ.get(env_name, "").strip()
    if not value:
        return None
    return None if value == (read_env_value(env_name) or "").strip() else value


def _env_lines(path: Path) -> tuple[list[str], str]:
    if not path.is_file():
        return [], "\n"
    # newline="" keeps CRLF visible: read_text() translates it, and a translated read makes every
    # Windows-authored .env look like an LF file, so the first write would rewrite all its lines.
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        raw = handle.read()
    return raw.splitlines(), ("\r\n" if "\r\n" in raw else "\n")


def _write_env_lines(path: Path, lines: list[str], newline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    path.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")
    if created:
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def _line_key(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("#") or "=" not in stripped:
        return ""
    return stripped.split("=", 1)[0].strip()


def read_env_value(key: str, env_path: Path | None = None) -> str | None:
    """The value ``key`` has in the env file Settings obeys, or None when that file does not set it."""
    path = env_path or effective_env_file()
    value: str | None = None
    for line in _env_lines(path)[0]:
        if _line_key(line) == key:
            value = line.strip().split("=", 1)[1].strip()
    return value


def write_env_value(key: str, value: str, env_path: Path | None = None) -> str | None:
    """Set ``key`` in the env file Settings obeys and return the value it replaced.

    Only matching lines are touched and the original line endings are kept: this file carries API keys,
    and re-rendering it through a parser would reorder or drop whatever is not modelled here. Duplicate
    assignments collapse into one, keeping the last value that was in force.
    """
    path = env_path or effective_env_file()
    lines, newline = _env_lines(path)
    previous: str | None = None
    out: list[str] = []
    written = False
    for line in lines:
        if _line_key(line) == key:
            previous = line.strip().split("=", 1)[1].strip()
            if not written:
                out.append(f"{key}={value}")
                written = True
            continue
        out.append(line)
    if not written:
        out.append(f"{key}={value}")
    _write_env_lines(path, out, newline)
    os.environ[key] = value
    return previous


def drop_env_value(key: str, env_path: Path | None = None) -> None:
    """Remove every assignment of ``key`` from the env file Settings obeys."""
    path = env_path or effective_env_file()
    lines, newline = _env_lines(path)
    kept = [line for line in lines if _line_key(line) != key]
    if len(kept) == len(lines):
        return
    _write_env_lines(path, kept, newline)
    os.environ.pop(key, None)


def honeytoken_hits() -> list[str]:
    """Names among this install's credentials that match a canary the build issued.

    Driven by ``HONEYTOKEN_API_KEYS``, the table that mints the canaries: the copy this replaced listed
    four names by hand, so ``GITHUB_TOKEN``, ``TELEGRAM_BOT_TOKEN`` and ``SLACK_BOT_TOKEN`` could carry
    a watermark through the gateway without ever being noticed. Both sources a running process resolves
    a name from are read — the environment and every env file.
    """
    from raven.core.watermark import HONEYTOKEN_API_KEYS

    hits: list[str] = []
    for name in HONEYTOKEN_API_KEYS:
        value = os.environ.get(name, "").strip()
        if not value:
            for path in env_file_candidates():
                for line in _env_lines(path)[0]:
                    if _line_key(line) == name:
                        value = line.strip().split("=", 1)[1].strip().strip("\"'")
        if value and is_honeytoken(name, value):
            hits.append(name)
    return hits


for _honeytoken_name in honeytoken_hits():
    logger.warning(honeytoken_warning(_honeytoken_name))
