from __future__ import annotations

import secrets
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
    """Write the fix where the gateway reads it, and name that file.

    This used to answer "AUTO-FIX: WEB_SECRET_KEY set to a5f3…" while storing the key in
    ``~/.raven/config.json``, which no running process and no later start ever read — the operator got a
    success message, a secret in their terminal history and the same failing check on the next run.
    """
    from raven.core.config import effective_env_file, write_env_value

    name = check.name
    where = effective_env_file()
    if name == "secret_key_prod":
        write_env_value("WEB_SECRET_KEY", secrets.token_hex(32))
        console.print(f"  [green]→ FIXED:[/green] a WEB_SECRET_KEY was written to [bold]{where}[/bold]")
        console.print("  [dim]it is not repeated here — a start reads it from that file[/dim]")
    elif name == "dm_policy":
        write_env_value("DM_POLICY", "pairing")
        console.print(f"  [green]→ FIXED:[/green] DM_POLICY=pairing written to [bold]{where}[/bold]")
    elif name == "rate_limiting":
        write_env_value("RATE_LIMIT_MAX", "60")
        console.print(f"  [green]→ FIXED:[/green] RATE_LIMIT_MAX=60 written to [bold]{where}[/bold]")
    else:
        console.print(f"  [dim]No auto-fix for '{name}'[/dim]")
