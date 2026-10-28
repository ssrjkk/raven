from __future__ import annotations

import json
import os
import sys

import click
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.core.config import Settings, settings
from raven.core.config_store import config_store

console = Console()

_EXEC_MODES = ("deny", "ask", "full")


def get_settings() -> Settings:
    """One seam for the configuration the posture block reads."""
    return settings


def security_posture_checks() -> list[tuple[str, str]]:
    """What the security settings on this install actually decide, not what they are called."""
    from raven.core.config import data_path
    from raven.core.features import FeatureFlags

    rows: list[tuple[str, str]] = []
    state = get_settings()

    mode = state.exec_security
    if mode == "deny":
        rows.append(("Tool Exec Policy", "[OK] deny — shell, python, browser, mcp_, plugin_, git writes, db_query refused"))
    elif mode == "ask":
        if state.exec_ask_mode == "off":
            rows.append(("Tool Exec Policy", "[!] ask with EXEC_ASK_MODE=off — exec runs without asking anyone"))
        else:
            rows.append(("Tool Exec Policy", f"[OK] ask ({state.exec_ask_mode}) — refused where nobody can be asked"))
    elif mode == "full":
        rows.append(("Tool Exec Policy", "[!] full — exec-class tools run with no confirmation"))
    else:
        rows.append(("Tool Exec Policy", f"[ERR] EXEC_SECURITY={mode!r} is not one of {list(_EXEC_MODES)}; every agent build raises"))

    if not state.workspace_only:
        rows.append(("Workspace Confinement", "[!] WORKSPACE_ONLY=false — path arguments are not confined"))
    elif state.resolved_workspace is None:
        rows.append(("Workspace Confinement", "[!] WORKSPACE_PATH is not set — workspace_only has no root to confine to"))
    else:
        rows.append(("Workspace Confinement", f"[OK] {state.resolved_workspace}"))

    overrides = data_path("tool_policy.json")
    rows.append(
        (
            "Tool Role Overrides",
            f"[OK] {overrides} exists — restricted tools need the role it grants" if overrides.exists() else "none — defaults apply",
        )
    )

    flags = FeatureFlags.get()
    telemetry = "on — local analytics only" if flags.is_enabled("telemetry") else "off"
    rows.append(("Features", f"{', '.join(flags.enabled_list()) or 'none'} (telemetry {telemetry})"))

    rows.append(_training_posture_row())

    return rows


def _training_posture_row() -> tuple[str, str]:
    """Fine-tuning is the one feature that can move model weights off the machine, so doctor says
    whether that door is open rather than leaving it to be inferred from what is installed."""
    import os

    from raven.unique.fine_tuning import training_tracking_enabled

    if training_tracking_enabled():
        return ("Finetune Tracking", "[!] RAVEN_TRAIN_TRACKING=on — metrics and checkpoint artifacts are published to api.wandb.ai")
    if os.environ.get("WANDB_API_KEY"):
        return ("Finetune Tracking", "[!] off, but WANDB_API_KEY is set: one RAVEN_TRAIN_TRACKING=on starts publishing weights")
    return ("Finetune Tracking", "[OK] off — training publishes nothing; corpus rows need consented=true and are PII-redacted")


@click.command()
def doctor():
    """Diagnose configuration, dependencies, and service health"""
    console.print(Panel.fit("[bold]Raven AI Doctor[/bold]"))
    checks = []

    config_store.load()
    cfg = config_store._data

    checks.append(
        ("Config Store", f"[OK] {config_store.path}" if config_store.path.exists() else "[!]️  Not initialized")
    )
    checks.append(("Python", sys.version))
    checks.append(("DB Path", str(settings.resolved_db_path)))

    has_any_key = bool(
        cfg.get("openrouter_api_key")
        or settings.openrouter_api_key.get_secret_value()
        or cfg.get("anthropic_api_key")
        or settings.anthropic_api_key.get_secret_value()
        or cfg.get("openai_api_key")
        or settings.openai_api_key.get_secret_value()
        or cfg.get("ollama_base_url")
        or settings.ollama_base_url
    )
    checks.append(("LLM Provider", "[OK] Configured" if has_any_key else "[!]️  No provider configured"))

    provider_names = []
    if cfg.get("openrouter_api_key") or settings.openrouter_api_key.get_secret_value():
        provider_names.append("OpenRouter")
    if cfg.get("anthropic_api_key") or settings.anthropic_api_key.get_secret_value():
        provider_names.append("Anthropic")
    if cfg.get("openai_api_key") or settings.openai_api_key.get_secret_value():
        provider_names.append("OpenAI")
    if cfg.get("ollama_base_url") or settings.ollama_base_url:
        provider_names.append("Ollama")
    if provider_names:
        checks.append(("Providers", ", ".join(provider_names)))

    checks.append(("Default Model", cfg.get("default_model") or settings.default_model or "—"))
    from raven.core.channel_config import configured_channels

    channel_list = configured_channels()
    checks.append(("Author", "ssrjkk (https://github.com/ssrjkk)"))
    checks.append(("Channels", ", ".join(channel_list) if channel_list else "[!]️  None configured"))
    checks.append(("DM Policy", cfg.get("dm_policy", "pairing")))
    checks.append(("Web Port", str(cfg.get("web_port") or settings.web_port)))
    checks.append(
        (
            "Web Secret Key",
            "[OK] Set" if (cfg.get("web_secret_key") or settings.web_secret_key.get_secret_value()) else "[!]️  Not set",
        )
    )

    import importlib.util

    has_crypto = importlib.util.find_spec("cryptography")
    checks.append(("Secrets Encryption", "[OK] Available" if has_crypto else "[!]️  Install cryptography for secrets"))

    if importlib.util.find_spec("win32serviceutil"):
        checks.append(("Windows Service", "[OK] pywin32 available"))
    elif sys.platform == "win32":
        checks.append(("Windows Service", "[!]️  Install pywin32 for service support"))

    if importlib.util.find_spec("playwright"):
        checks.append(("Playwright", "[OK] Installed"))
    else:
        checks.append(("Playwright", "[!]️  Not installed (browser plugin limited)"))

    api_ok = False
    try:
        import httpx

        r = httpx.get(f"http://localhost:{settings.web_port}/api/status", timeout=3)
        api_ok = r.is_success
    except Exception as e:
        logger.debug("Doctor health check failed: {}", e)
    checks.append(("API", "[OK] Running" if api_ok else "[ERR] Stopped"))

    mcp_raw = settings.mcp_servers
    if mcp_raw:
        try:
            mcp_servers = json.loads(mcp_raw)
            mcp_status = f"{len(mcp_servers)} configured"
        except json.JSONDecodeError:
            mcp_status = "[!] Invalid JSON"
        checks.append(("MCP Servers", mcp_status))

    sb_policy = settings.channel_sandbox_policy
    if sb_policy:
        sb_status = "[OK] Configured"
        try:
            json.loads(sb_policy)
        except json.JSONDecodeError:
            sb_status = "[!] Invalid JSON"
        checks.append(("Channel Sandbox Policy", sb_status))

    checks.extend(security_posture_checks())

    table = Table(show_header=False)
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    for name, result in checks:
        table.add_row(name, result)
    console.print(table)

    if not api_ok and not any(key in os.environ.get("RUNNING_TESTS", "") for key in ("1", "true")):
        console.print("\n[yellow]Raven is not running. Start it with: raven start[/yellow]")
