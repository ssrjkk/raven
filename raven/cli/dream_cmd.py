from __future__ import annotations

import asyncio
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from raven.core.config import settings
from raven.core.db import DatabaseFactory
from raven.core.dreaming.engine import DreamEngine
from raven.core.features import FeatureFlags
from raven.core.memory.manager import MemoryManager

console = Console()


def _try_api(path: str) -> dict[str, Any] | None:
    import httpx
    try:
        resp = httpx.get(f"http://localhost:{settings.web_port}{path}", timeout=5)
        if resp.is_success:
            data: dict[str, Any] = resp.json()
            return data
    except Exception:
        return None
    return None


@click.group()
def dream_group() -> None:
    """Dream engine management"""


@dream_group.command()
def status() -> None:
    """Show dream engine status"""
    data = _try_api("/api/dream/status")
    if data:
        table = Table(title="Dream Engine")
        table.add_column("Property", style="cyan")
        table.add_column("Value")
        table.add_row("Running", str(data.get("running", "?")))
        console.print(table)
        return

    offline = not FeatureFlags.get().is_enabled("dreaming")
    table = Table(title="Dream Engine (offline)")
    table.add_column("Property", style="cyan")
    table.add_column("Value")
    table.add_row("Feature Enabled", "No" if offline else "Yes")
    table.add_row("Gateway", "Not running")
    console.print(table)


@dream_group.command()
def cycle() -> None:
    """Trigger one dream cycle"""
    import httpx
    try:
        resp = httpx.post(f"http://localhost:{settings.web_port}/api/dream/cycle", timeout=120)
        if resp.is_success:
            data = resp.json()
            stats = data.get("stats", {})
            table = Table(title="Dream Cycle Results")
            table.add_column("Metric", style="cyan")
            table.add_column("Value")
            for k, v in stats.items():
                table.add_row(k, str(v))
            console.print(table)
            return
    except httpx.ConnectError:
        pass

    console.print("[yellow]Gateway not running. Running local cycle...[/yellow]")

    async def _local_cycle():
        db = DatabaseFactory.create()
        await db.connect()
        memory = MemoryManager(db=db, workspace=settings.resolved_workspace)
        engine = DreamEngine(memory=memory)
        stats = await engine.cycle_once()
        await db.disconnect()
        return stats

    stats = asyncio.run(_local_cycle())
    table = Table(title="Dream Cycle Results (local)")
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    for k, v in stats.items():
        table.add_row(k, str(v))
    console.print(table)
