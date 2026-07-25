from __future__ import annotations

import json
import os
import sys

import click
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.core.config import settings
from raven.core.config_store import config_store

console = Console()


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

    table = Table(show_header=False)
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    for name, result in checks:
        table.add_row(name, result)
    console.print(table)

    if not api_ok and not any(key in os.environ.get("RUNNING_TESTS", "") for key in ("1", "true")):
        console.print("\n[yellow]Raven is not running. Start it with: raven start[/yellow]")
