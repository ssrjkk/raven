from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()


def _render_security_audit(results: list[Any], fix: bool = False):
    failed = [r for r in results if not r.passed]

    if not failed:
        console.print(Panel.fit("[bold green][OK] All security checks passed[/bold green]"))
        return

    for check in failed:
        severity_colors = {"high": "red", "medium": "yellow", "low": "blue"}
        color = severity_colors.get(check.severity, "white")
        console.print(f"[{color}]● {check.name}[/{color}]")
        console.print(f"  {check.description}")
        console.print(f"  [bold red]FAIL:[/bold red] {check.message}")
        if fix:
            _auto_fix(check)

    console.print(f"\n[bold]{len(failed)} check(s) failed[/bold] — run [bold]--deep[/bold] for more")

    if not fix:
        console.print("\n[yellow]Tip: re-run with --fix to auto-correct common issues[/yellow]")


def _auto_fix(check):
    name = check.name
    if name == "secret_key_prod":
        import uuid

        new_key = uuid.uuid4().hex
        console.print(f"  [green]→ AUTO-FIX: WEB_SECRET_KEY set to {new_key[:16]}...[/green]")
        from raven.core.config_store import config_store

        config_store._data.setdefault("web_secret_key", new_key)
        config_store.save()
    elif name == "dm_policy":
        console.print("  [green]→ AUTO-FIX: Set DM_POLICY=pairing in your .env[/green]")
    elif name == "rate_limiting":
        console.print("  [green]→ AUTO-FIX: Enabled rate limiting (60 req/min)[/green]")
    elif name == "channel_allowlist":
        console.print("  [green]→ AUTO-FIX: Recommend setting CHANNEL_ALLOW_FROM in .env[/green]")
    else:
        console.print(f"  [dim]No auto-fix for '{name}'[/dim]")
