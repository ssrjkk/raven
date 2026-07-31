from __future__ import annotations

import time as _time
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.table import Table

from raven.core.config import settings

console = Console()


@click.group(name="backup")
def backup_group() -> None:
    """Backup and restore memory"""


@backup_group.command()
@click.option("--output", "-o", default=None, help="Output file path")
def export(output: str | None) -> None:
    """Export all memory tiers to a JSON backup file"""
    try:
        resp = httpx.post(f"http://localhost:{settings.web_port}/api/memory/backup", timeout=30)
        resp.raise_for_status()
        data = resp.json()
        path = data.get("path", "unknown")
        console.print(f"[green]Memory exported to {path}[/green]")
    except httpx.RequestError as e:
        console.print(f"[red]Failed to connect to gateway: {e}[/red]")
        console.print("[yellow]Make sure the gateway is running with: raven start[/yellow]")
        raise SystemExit(1) from e


@backup_group.command()
@click.argument("path", type=click.Path(exists=True))
def restore(path: str) -> None:
    """Restore memory from a JSON backup file"""
    try:
        resp = httpx.post(
            f"http://localhost:{settings.web_port}/api/memory/restore",
            json={"path": str(Path(path).resolve())},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ok"):
            restored = data.get("restored", {})
            console.print(f"[green]Restored {sum(restored.values())} memory entries[/green]")
            for tier, count in restored.items():
                console.print(f"  {tier}: {count}")
        else:
            console.print(f"[red]Restore failed: {data.get('error', 'unknown')}[/red]")
    except httpx.RequestError as e:
        console.print(f"[red]Failed to connect to gateway: {e}[/red]")
        console.print("[yellow]Make sure the gateway is running with: raven start[/yellow]")
        raise SystemExit(1) from e


@backup_group.command(name="list")
def list_backups() -> None:
    """List available memory backups"""
    try:
        resp = httpx.get(f"http://localhost:{settings.web_port}/api/memory/backups", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        backups = data.get("backups", [])
        if not backups:
            console.print("[yellow]No backups found[/yellow]")
            return
        table = Table(title="Memory Backups")
        table.add_column("File", style="cyan")
        table.add_column("Size", style="green")
        table.add_column("Modified")
        for b in backups:
            modified = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(b["modified"]))
            size = f"{b['size_bytes'] / 1024:.1f} KB"
            table.add_row(b["filename"], size, modified)
        console.print(table)
    except httpx.RequestError as e:
        console.print(f"[red]Failed to connect to gateway: {e}[/red]")
        console.print("[yellow]Make sure the gateway is running with: raven start[/yellow]")
        raise SystemExit(1) from e
