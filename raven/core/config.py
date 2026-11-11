from __future__ import annotations

import contextlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any
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

# Env names a running gateway is expected to honour without a restart. Anything secret, port-shaped
# or storage-shaped stays out: those need a fresh process because their consumers cache connections.
_RUNTIME_SWITCHABLE: dict[str, str] = {
    "DEFAULT_MODEL": "default_model",
    "MODEL_FAST": "model_fast",
    "MODEL_BALANCED": "model_balanced",
    "MODEL_QUALITY": "model_quality",
    "OLLAMA_BASE_URL": "ollama_base_url",
}


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


def refresh_settings_from_env() -> list[str]:
    """Copy the runtime-switchable env names onto the live settings object and name what moved.

    ``Settings`` reads the environment once, at import, so editing ``DEFAULT_MODEL`` in ``.env`` used to
    change only the next process while the running gateway kept answering from the old model.
    ``ConfigWatcher`` keeps ``os.environ`` current and calls this. An empty value is skipped: an unset
    name must not wipe an auto-discovered model.
    """
    changed: list[str] = []
    s = get_settings()
    for env_name, attr in _RUNTIME_SWITCHABLE.items():
        value = os.environ.get(env_name, "").strip()
        if not value or getattr(s, attr, None) == value:
            continue
        setattr(s, attr, value)
        changed.append(env_name)
    if changed:
        logger.info("[config] runtime switch applied: {}", ", ".join(changed))
    return changed


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
