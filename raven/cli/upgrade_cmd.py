from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
def upgrade():
    """Update Raven AI to the latest version"""
    repo = Path(__file__).resolve().parent.parent.parent
    os.chdir(str(repo))
    console.print("[bold]Raven Upgrade[/bold]\n")
    if (repo / ".git").is_dir():
        console.print("[*] Pulling latest code...")
        r = subprocess.run(["git", "pull", "--rebase"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
        if r.returncode != 0:
            console.print(f"[red]Git pull failed: {r.stderr.strip()}[/red]")
            raise SystemExit(1)
        console.print("[green]  OK[/green]")
    console.print("[*] Updating Python dependencies...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
    if r.returncode != 0:
        console.print(f"[yellow]pip install warning: {r.stderr.strip()}[/yellow]")
    else:
        console.print("[green]  OK[/green]")
    web_dir = repo / "web"
    if web_dir.is_dir() and (web_dir / "package.json").is_file():
        console.print("[*] Updating web frontend...")
        r = subprocess.run(["npm", "install"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(web_dir), timeout=120, check=False)
        if r.returncode == 0:
            console.print("[green]  OK[/green]")
    console.print("\n[green]Upgrade complete! Run 'raven start' to apply.[/green]")
