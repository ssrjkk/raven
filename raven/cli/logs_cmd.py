from __future__ import annotations

import re
import time
from typing import Any

import click
from loguru import logger
from rich.console import Console

from raven.core._json import json
from raven.core.config import settings

console = Console()

_LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
_STYLES = {"DEBUG": "dim", "INFO": "", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}
_PLAIN_LEVEL = re.compile(r"\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|")


def _render_line(line: str) -> tuple[str, str] | None:
    """Turn one raw log line into (level, text), or None when it carries no known level.

    The file sink writes JSON lines; lines in the old padded loguru shape are still accepted so a
    log started before this change stays readable.
    """
    text = line.rstrip("\n")
    if not text.strip():
        return None
    if text.startswith("{"):
        try:
            record: dict[str, Any] = json.loads(text)
        except ValueError:
            return None
        level = str(record.get("level", ""))
        if level not in _LEVELS:
            return None
        rendered = "{} | {:<8} | {} - {}".format(
            record.get("timestamp", ""),
            level,
            record.get("module", ""),
            record.get("message", ""),
        )
        if record.get("correlation_id"):
            rendered += f" [{record['correlation_id']}]"
        return level, rendered
    match = _PLAIN_LEVEL.search(text)
    if not match:
        return None
    return match.group(1), text


@click.command()
@click.option("--lines", "-n", default=50, type=int, help="Number of lines to show")
@click.option("--level", "-l", default="DEBUG", help="Minimum log level (DEBUG, INFO, WARNING, ERROR)")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
def logs(lines: int, level: str, follow: bool):
    """View Raven AI logs"""
    log_path = settings.resolved_log_file
    if not log_path.exists():
        console.print("[red]No log file found. Set LOG_FILE or run 'raven start' first.[/red]")
        raise SystemExit(1)
    min_level = _LEVELS.get(level.upper(), 0)
    try:
        with log_path.open(encoding="utf-8") as f:
            all_lines = f.readlines()
        rendered = []
        for line in all_lines[-lines * 10 :]:
            entry = _render_line(line)
            if entry and _LEVELS[entry[0]] >= min_level:
                rendered.append(entry)
        for lvl, text in rendered[-lines:]:
            console.print(text, style=_STYLES.get(lvl, ""), markup=False)
        if follow:
            console.print("[dim]--- watching for new logs (Ctrl+C to stop) ---[/dim]")
            try:
                with log_path.open(encoding="utf-8") as f:
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            entry = _render_line(line)
                            if entry and _LEVELS[entry[0]] >= min_level:
                                console.print(entry[1], style=_STYLES.get(entry[0], ""), markup=False)
                        else:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                logger.debug("[logs] follow interrupted by user")
            except Exception as exc:
                console.print(f"[red]Log follow error: {exc}[/red]")
    except Exception as exc:
        console.print(f"[red]Error reading logs: {exc}[/red]")
