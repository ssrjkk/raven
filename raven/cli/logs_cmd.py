from __future__ import annotations

import os
import time
from pathlib import Path

import click
from loguru import logger
from rich.console import Console

console = Console()


@click.command()
@click.option("--lines", "-n", default=50, type=int, help="Number of lines to show")
@click.option("--level", "-l", default="DEBUG", help="Minimum log level (DEBUG, INFO, WARNING, ERROR)")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
def logs(lines: int, level: str, follow: bool):
    """View Raven AI logs"""
    env_path = os.environ.get("RAVEN_LOG_FILE")
    log_path: Path | None
    if env_path:
        log_path = Path(env_path)
    else:
        candidates = [
            Path("data/logs/raven.log"),
            Path("raven.log"),
            Path.home() / ".raven" / "logs" / "raven.log",
        ]
        log_path = next((p for p in candidates if p.exists()), None)
    if log_path is None or not log_path.exists():
        console.print("[red]No log file found. Set RAVEN_LOG_FILE env var or run 'raven start' first.[/red]")
        raise SystemExit(1)
    levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level = levels.get(level.upper(), 0)
    try:
        with log_path.open(encoding="utf-8") as f:
            all_lines = f.readlines()
        filtered = []
        for line in all_lines[-lines * 10:]:
            for lvl, lvl_id in levels.items():
                if lvl_id >= min_level and f"| {lvl} |" in line:
                    filtered.append((lvl, line.rstrip()))
                    break
        shown = filtered[-lines:] if len(filtered) > lines else filtered
        for lvl, line in shown:
            style = {"DEBUG": "dim", "INFO": "", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}
            console.print(f"[{style.get(lvl, '')}]{line}[/{style.get(lvl, '')}]")
        if follow:
            console.print("[dim]--- watching for new logs (Ctrl+C to stop) ---[/dim]")
            try:
                with log_path.open(encoding="utf-8") as f:
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            console.print(line.rstrip())
                        else:
                            time.sleep(0.5)  # noqa: ASYNC100 — sync CLI, not async
            except KeyboardInterrupt:
                logger.debug("[logs] follow interrupted by user")
            except Exception as exc:
                console.print(f"[red]Log follow error: {exc}[/red]")
    except Exception as exc:
        console.print(f"[red]Error reading logs: {exc}[/red]")
