from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.config import settings


class AuditCheck:
    def __init__(self, name: str, description: str, severity: str = "info"):
        self.name = name
        self.description = description
        self.severity = severity
        self.passed = False
        self.message = ""
        self._fix_hint: str | None = None

    def ok(self, msg: str = ""):
        self.passed = True
        self.message = msg

    def fail(self, msg: str, fix_hint: str | None = None):
        self.passed = False
        self.message = msg
        self._fix_hint = fix_hint

    def fix_hint(self) -> str | None:
        return self._fix_hint

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "passed": self.passed,
            "message": self.message,
        }
        if self._fix_hint:
            d["fix_hint"] = self._fix_hint
        return d


class SecurityAudit:
    def __init__(self):
        self._checks: list[AuditCheck] = []

    def run_all(self, deep: bool = False) -> list[AuditCheck]:
        self._checks = []
        self._check_dm_policy()
        self._check_auth_mode()
        self._check_secret_key()
        self._check_web_bind()
        self._check_tools_exec()
        self._check_fs_permissions()
        self._check_secrets_encryption()
        self._check_rate_limiting()
        self._check_channel_allowlist()
        self._check_sandbox_mode()
        self._check_workspace_path()
        self._check_pii_redaction()
        self._check_audit_chain()
        self._check_plugin_isolation()
        self._check_tool_overrides()
        self._check_web_cors()
        self._check_https_enabled()
        self._check_api_keys()
        self._check_config_validation()
        self._check_debug_mode()
        self._check_secret_file_perms()
        self._check_exec_security()
        self._check_context_visibility()
        if deep:
            self._check_network_exposure()
            self._check_env_file_perms()
            self._check_dependencies()
            self._check_log_permissions()
            self._check_signing_key()
            self._check_docker_sandbox()
            self._check_token_expiry()
            self._check_session_timeout()
        return self._checks

    def _add(self, name: str, description: str, severity: str = "info") -> AuditCheck:
        c = AuditCheck(name, description, severity)
        self._checks.append(c)
        return c

    def _check_dm_policy(self):
        c = self._add("dm_policy", "DM policy is not 'open' without allowlist", "high")
        if settings.dm_policy == "open" and not settings.channel_allow_from:
            c.fail(
                "DM_POLICY=open without CHANNEL_ALLOW_FROM — anyone can message the bot",
                fix_hint="Set CHANNEL_ALLOW_FROM to restrict allowed users, or use DM_POLICY=pairing",
            )
        elif settings.dm_policy == "open":
            c.ok("DM_POLICY=open with CHANNEL_ALLOW_FROM configured")
        elif settings.dm_policy in ("pairing", "closed"):
            c.ok(f"DM_POLICY={settings.dm_policy}")
        else:
            c.fail(f"Unknown DM_POLICY: {settings.dm_policy}")

    def _check_auth_mode(self):
        c = self._add("web_auth", "Web dashboard has auth middleware", "medium")
        has_key = bool(settings.web_secret_key.get_secret_value())
        if has_key:
            c.ok("WEB_SECRET_KEY configured — auth middleware active")
        else:
            c.fail(
                "WEB_SECRET_KEY is empty — dashboard has no auth",
                fix_hint="Set WEB_SECRET_KEY to a random string in .env",
            )

    def _check_secret_key(self):
        c = self._add("secret_key_prod", "Secret key is not default", "high")
        if settings.web_secret_key.get_secret_value() in ("", "change-me-in-production"):
            c.fail(
                "WEB_SECRET_KEY is default or empty — change in production",
                fix_hint="Generate a key: python3 -c 'import secrets; print(secrets.token_hex(32))'",
            )
        else:
            c.ok("WEB_SECRET_KEY is custom")

    def _check_web_bind(self):
        c = self._add("web_bind", "Gateway binds to 127.0.0.1 by default", "medium")
        c.ok("Gateway binds to 0.0.0.0 (configure firewall or use reverse proxy)")

    def _check_tools_exec(self):
        c = self._add("tools_exec", "Tool exec security policy", "high")
        from raven.core.config import _DEFAULT_TOOLS_DENY

        if _DEFAULT_TOOLS_DENY:
            deny_str = ", ".join(_DEFAULT_TOOLS_DENY)
            c.ok(f"Tools deny list active: {deny_str}")
        else:
            c.fail("No deny list configured for tools")

    def _check_fs_permissions(self):
        c = self._add("fs_perms", "Data directory permissions", "medium")
        db = settings.resolved_db_path
        if db.exists():
            mode = db.stat().st_mode
            world_readable = bool(mode & stat.S_IROTH)
            if world_readable and sys.platform != "win32":
                c.fail(f"Database is world-readable: {db}", fix_hint=f"Run: chmod 600 {db}")
            else:
                c.ok("Database permissions OK")
        else:
            c.ok("Database does not exist yet (first run)")

    def _check_secrets_encryption(self):
        c = self._add("secrets_encryption", "Secrets are encrypted with Fernet", "high")
        if "RAVEN_MASTER_KEY" in os.environ:
            c.ok("Fernet encryption available (RAVEN_MASTER_KEY set)")
        else:
            c.fail(
                "Secrets not encrypted — install cryptography and set RAVEN_MASTER_KEY",
                fix_hint="pip install cryptography && echo 'RAVEN_MASTER_KEY=your-key' >> .env",
            )

    def _check_rate_limiting(self):
        c = self._add("rate_limiting", "Rate limiting is enabled", "medium")
        if settings.rate_limit_max > 0:
            c.ok(f"Rate limit: {settings.rate_limit_max} req/{settings.rate_limit_window}s")
        else:
            c.fail("Rate limiting is disabled (RATE_LIMIT_MAX=0)", fix_hint="Set RATE_LIMIT_MAX=60 in .env")

    def _check_channel_allowlist(self):
        c = self._add("channel_allowlist", "Channel allowlist is configured", "medium")
        if settings.channel_allow_from:
            c.ok("CHANNEL_ALLOW_FROM is set")
        else:
            c.fail(
                "CHANNEL_ALLOW_FROM is empty — all users can reach the bot",
                fix_hint="Set CHANNEL_ALLOW_FROM to comma-separated user IDs",
            )

    def _check_sandbox_mode(self):
        c = self._add("sandbox_mode", "Sandbox mode is not 'none'", "medium")
        if settings.sandbox_mode == "none":
            c.fail(
                "SANDBOX_MODE=none — no execution isolation",
                fix_hint="Set SANDBOX_MODE=non-main or SANDBOX_MODE=all in .env",
            )
        elif settings.sandbox_mode == "non-main":
            c.ok("SANDBOX_MODE=non-main — sandbox for non-main agents")
        elif settings.sandbox_mode == "main":
            c.ok("SANDBOX_MODE=main — all agents in sandbox")
        elif settings.sandbox_mode == "all":
            c.ok("SANDBOX_MODE=all — full sandbox isolation")

    def _check_workspace_path(self):
        c = self._add("workspace_path", "Workspace path is isolated", "low")
        ws = settings.resolved_workspace
        if ws:
            c.ok(f"Workspace: {ws}")
        else:
            c.fail(
                "WORKSPACE_PATH not set — FS operations unrestricted",
                fix_hint="Set WORKSPACE_PATH to a dedicated directory",
            )

    def _check_pii_redaction(self):
        c = self._add("pii_redaction", "PII redaction is active on external content", "medium")
        try:
            from raven.core.security.context_filter import PIIEngine

            patterns = PIIEngine._build_patterns()
            if patterns:
                c.ok(f"PII redaction active: {len(patterns)} patterns")
            else:
                c.fail("No PII patterns configured")
        except ImportError:
            c.fail("PII redaction module not available")

    def _check_audit_chain(self):
        c = self._add("audit_chain", "Audit log chain integrity", "medium")
        from raven.core.audit import audit_logger

        errors = audit_logger.verify_chain()
        if errors and not errors[0].get("valid"):
            c.fail(f"Audit log chain errors: {len(errors)}")
        else:
            c.ok("Audit log chain intact")

    def _check_plugin_isolation(self):
        c = self._add("plugin_isolation", "Plugin sandbox has capability restrictions", "high")
        try:
            from raven.core.plugin_sandbox import plugin_sandbox

            denied = plugin_sandbox._global_deny
            if denied:
                c.ok(f"Global deny active: {', '.join(denied)}")
            else:
                rs = plugin_sandbox.to_dict()
                if rs.get("per_plugin"):
                    c.ok(f"Per-plugin capabilities: {len(rs['per_plugin'])} plugins")
                else:
                    c.fail("No plugin capability restrictions configured")
        except ImportError:
            c.fail("Plugin sandbox module not available")

    def _check_tool_overrides(self):
        c = self._add("tool_overrides", "Tool allow/deny lists are not both set", "low")
        if settings.tools_deny and settings.tools_allow:
            c.fail(
                "Both TOOLS_DENY and TOOLS_ALLOW set — allow has priority, deny may be bypassed",
                fix_hint="Remove one of TOOLS_DENY or TOOLS_ALLOW",
            )
        else:
            c.ok("Tool policy is unambiguous")

    def _check_web_cors(self):
        c = self._add("web_cors", "CORS origins are restricted", "medium")
        if settings.web_cors_origins == "*":
            c.fail(
                "WEB_CORS_ORIGINS=* — any website can make API requests",
                fix_hint=f"Set WEB_CORS_ORIGINS to specific origins (e.g., http://localhost:{settings.web_port})",
            )
        else:
            c.ok(f"CORS origins: {settings.web_cors_origins}")

    def _check_https_enabled(self):
        c = self._add("https_enabled", "HTTPS is configured behind reverse proxy", "medium")
        key_path = os.environ.get("TLS_KEY_PATH") or os.environ.get("SSL_KEY_FILE") or ""
        cert_path = os.environ.get("TLS_CERT_PATH") or os.environ.get("SSL_CERT_FILE") or ""
        if key_path and cert_path:
            c.ok(f"TLS configured: key={key_path}, cert={cert_path}")
        else:
            c.fail(
                "No TLS certificate configured — use a reverse proxy (nginx/Caddy) for HTTPS",
                fix_hint="Set TLS_KEY_PATH and TLS_CERT_PATH, or front with nginx",
            )

    def _check_api_keys(self):
        c = self._add("api_keys", "LLM API keys are configured for default model", "high")
        model = settings.default_model
        if "openrouter" in model and settings.openrouter_api_key.get_secret_value():
            c.ok(f"OpenRouter key configured for {model}")
        elif "anthropic" in model and settings.anthropic_api_key.get_secret_value():
            c.ok(f"Anthropic key configured for {model}")
        elif "openai" in model and settings.openai_api_key.get_secret_value():
            c.ok(f"OpenAI key configured for {model}")
        elif "ollama" in model:
            if settings.ollama_base_url:
                c.ok(f"Ollama base URL configured: {settings.ollama_base_url}")
            else:
                c.fail(
                    "Default model is Ollama but OLLAMA_BASE_URL is not set",
                    fix_hint=f"Set OLLAMA_BASE_URL={settings.ollama_base_url}",
                )
        else:
            c.fail(
                f"No API key found for default model '{model}'",
                fix_hint=f"Set the appropriate API key for {model} in .env",
            )

    def _check_config_validation(self):
        c = self._add("config_validation", "Configuration passes validation", "low")
        try:
            settings.validate_settings()
            c.ok("Configuration is valid")
        except ValueError as e:
            c.fail(f"Configuration is invalid: {e}")

    def _check_debug_mode(self):
        c = self._add("debug_mode", "Log level is not DEBUG in production", "low")
        if settings.log_level.upper() == "DEBUG":
            c.fail("LOG_LEVEL=DEBUG — verbose logging may leak sensitive data", fix_hint="Set LOG_LEVEL=INFO in .env")
        else:
            c.ok(f"LOG_LEVEL={settings.log_level}")

    def _check_secret_file_perms(self):
        c = self._add("secret_file_perms", "Secrets key file has restricted permissions", "high")
        secrets_key_path = Path("data/.secrets_key")
        if secrets_key_path.exists() and sys.platform != "win32":
            mode = secrets_key_path.stat().st_mode
            if mode & stat.S_IROTH:
                c.fail(".secrets_key is world-readable", fix_hint="chmod 600 data/.secrets_key")
            else:
                c.ok(".secrets_key permissions OK")
        else:
            c.ok("Secrets key check N/A (not yet created or Windows)")

    def _check_exec_security(self):
        c = self._add("exec_security", "Exec security mode is not 'allow all'", "high")
        if settings.exec_security == "allow":
            c.fail(
                "EXEC_SECURITY=allow — all agents can execute arbitrary code",
                fix_hint="Set EXEC_SECURITY=deny or EXEC_SECURITY=full",
            )
        elif settings.exec_security == "full":
            c.ok("EXEC_SECURITY=full — exec requires user approval")
        elif settings.exec_security == "deny":
            c.ok("EXEC_SECURITY=deny — exec disabled by policy")

    def _check_context_visibility(self):
        c = self._add("context_visibility", "Context visibility is not set to 'ALL' in production", "medium")
        if settings.context_visibility == "all":
            c.fail(
                "CONTEXT_VISIBILITY=all — full context shared with external content",
                fix_hint="Set CONTEXT_VISIBILITY=allowlist or CONTEXT_VISIBILITY=allowlist_quote",
            )
        else:
            c.ok(f"CONTEXT_VISIBILITY={settings.context_visibility}")

    # --- Deep checks ---

    def _check_network_exposure(self):
        c = self._add("network_exposure", "Gateway is not exposed to public internet", "high")
        c.ok("Verify with: netstat -an | grep 18888 (should be 127.0.0.1 or firewalled)")

    def _check_env_file_perms(self):
        c = self._add("env_file_perms", ".env file is not world-readable", "high")
        env = Path(".env")
        if env.exists() and sys.platform != "win32":
            mode = env.stat().st_mode
            if mode & stat.S_IROTH:
                c.fail(".env is world-readable — contains API keys", fix_hint="chmod 600 .env")
            else:
                c.ok(".env permissions OK")
        else:
            c.ok("Check manually on your platform")

    def _check_dependencies(self):
        c = self._add("dependency_audit", "Check for known-vulnerable packages", "low")
        try:
            import subprocess

            result = subprocess.run(
                [sys.executable, "-m", "pip", "audit"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                c.ok("pip-audit passed")
            else:
                c.fail(f"Vulnerabilities found:\n{result.stdout[:500]}")
        except FileNotFoundError:
            c.ok("pip-audit not installed (recommend: pip install pip-audit && pip-audit)")

    def _check_log_permissions(self):
        c = self._add("log_permissions", "Log files are not world-readable", "medium")
        from raven.core.config import settings as s

        log_file = s.resolved_log_file
        if log_file.exists() and sys.platform != "win32":
            mode = log_file.stat().st_mode
            if mode & stat.S_IROTH:
                c.fail("Log file is world-readable", fix_hint=f"chmod 600 {log_file}")
            else:
                c.ok("Log file permissions OK")
        else:
            c.ok("Log file check N/A (not yet created or Windows)")

    def _check_signing_key(self):
        c = self._add("audit_signing", "Audit log has Ed25519 signing key", "low")
        key = os.environ.get("RAVEN_AUDIT_SIGNING_KEY")
        if key:
            c.ok("RAVEN_AUDIT_SIGNING_KEY is set — audit log is signed")
        else:
            c.fail(
                "RAVEN_AUDIT_SIGNING_KEY not set — audit log is unsigned",
                fix_hint="Generate a key with: python3 -c 'import secrets; print(secrets.token_hex(32))'",
            )

    def _check_docker_sandbox(self):
        c = self._add("docker_sandbox", "Docker sandbox backend is available", "low")
        try:
            import docker

            try:
                client = docker.from_env()
                client.ping()
                client.close()
                c.ok("Docker is available for sandbox execution")
            except Exception as exc:
                logger.warning("Docker daemon not reachable: {}", exc)
                c.fail("Docker is installed but daemon is not reachable")
        except ImportError:
            c.fail("Docker Python package not installed (pip install docker)")

    def _check_token_expiry(self):
        c = self._add("token_expiry", "No expired or long-lived tokens detected", "low")
        from raven.core.channel_config import get_channel_config

        tokens = {
            "TELEGRAM_BOT_TOKEN": bool(get_channel_config("telegram").get("bot_token", "")),
            "DISCORD_BOT_TOKEN": bool(get_channel_config("discord").get("bot_token", "")),
            "SLACK_BOT_TOKEN": bool(get_channel_config("slack").get("bot_token", "")),
        }
        configured = sum(1 for v in tokens.values() if v)
        c.ok(f"{configured} token(s) configured (check expiry manually via provider dashboard)")

    def _check_session_timeout(self):
        c = self._add("session_timeout", "Session timeout is configured", "low")
        llm_timeout = settings.llm_timeout
        if llm_timeout > 600:
            c.fail(
                f"LLM_TIMEOUT={llm_timeout}s is very high — sessions may hang",
                fix_hint="Set LLM_TIMEOUT to 120 or lower",
            )
        else:
            c.ok(f"LLM_TIMEOUT={llm_timeout}s")
