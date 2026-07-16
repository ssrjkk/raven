from __future__ import annotations

import asyncio
import contextlib
import time

import click
from rich.console import Console
from rich.table import Table

from raven.core.config import settings

console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@click.group(name="monitor")
def monitor_group():
    """Manage monitors (HTTP, price, RSS, file, process)"""


@monitor_group.command("list")
@click.option("--user", default=None, help="Filter by user ID")
@click.option("--status", default=None, help="Filter by status (active/paused)")
def monitor_list(user: str | None, status: str | None):
    """List all monitors"""
    async def _inner():
        from raven.core.monitor.store import MonitorStore

        store = MonitorStore(settings.resolved_db_path)
        monitors = await store.list_monitors(user_id=user, status=status)
        if not monitors:
            console.print("[yellow]No monitors configured[/yellow]")
            return
        table = Table(title="Monitors")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Type", style="blue")
        table.add_column("Target", style="dim")
        table.add_column("Interval", style="green")
        table.add_column("Status")
        table.add_column("Last Check")
        for m in monitors:
            icon = {"active": "[OK]", "paused": "[||]", "error": "[ERR]"}.get(m.status.value, "[?]")
            last = ""
            if m.last_check:
                last = f"{'[OK]' if m.last_check.status == 'up' else '[NO]'} {m.last_check.checked_at:.0f}s ago"
            table.add_row(
                m.id[:8], m.name, m.type.value, m.target[:40], f"{m.interval_seconds}s", f"{icon} {m.status.value}", last
            )
        console.print(table)
    _run_async(_inner())


@monitor_group.command("add")
@click.option("--name", required=True, help="Monitor name")
@click.option("--type", "mon_type", required=True, type=click.Choice(["http", "price", "rss", "file", "process"]))
@click.option("--target", required=True, help="URL, symbol, path, or process name")
@click.option("--interval", default=300, type=int, help="Check interval in seconds")
@click.option("--condition", "conditions", multiple=True, help="Condition (e.g. status_code!=200)")
@click.option("--user", default="cli", help="User ID")
def monitor_add(name: str, mon_type: str, target: str, interval: int, conditions: tuple[str], user: str):
    """Add a new monitor"""
    async def _inner():
        from raven.core.monitor.models import Condition, ConditionOperator, Monitor, MonitorStatus, MonitorType
        from raven.core.monitor.store import MonitorStore

        parsed_conditions = []
        for c in conditions:
            parts = (
                c.split("!", 1)
                if "!" in c
                else c.split("=", 1)
                if "=" in c
                else c.split(">", 1)
                if ">" in c
                else c.split("<", 1)
                if "<" in c
                else [c, ""]
            )
            if len(parts) == 2:
                op_str = "!=" if "!" in c else "=" if "=" in c else ">" if ">" in c else "<"
                op_map = {
                    "=": ConditionOperator.EQ,
                    "!=": ConditionOperator.NE,
                    ">": ConditionOperator.GT,
                    "<": ConditionOperator.LT,
                }
                raw_val: str = parts[1]
                parsed_val: int | float | str = raw_val
                try:
                    parsed_val = int(raw_val)
                except ValueError:
                    with contextlib.suppress(ValueError):
                        parsed_val = float(raw_val)
                parsed_conditions.append(
                    Condition(metric=parts[0].strip(), operator=op_map.get(op_str, ConditionOperator.EQ), value=parsed_val)
                )

        monitor = Monitor(
            name=name,
            type=MonitorType(mon_type),
            target=target,
            interval_seconds=interval,
            status=MonitorStatus.ACTIVE,
            conditions=parsed_conditions,
            user_id=user,
        )
        store = MonitorStore(settings.resolved_db_path)
        await store.save_monitor(monitor)
        console.print(f"[green]Monitor '{name}' ({monitor.id[:8]}) added[/green]")
        if parsed_conditions:
            for cond in parsed_conditions:
                console.print(f"  [!] Condition: {cond.metric} {cond.operator.value} {cond.value}")
    _run_async(_inner())


@monitor_group.command("remove")
@click.argument("monitor_id")
def monitor_remove(monitor_id: str):
    """Remove a monitor"""
    async def _inner():
        from raven.core.monitor.store import MonitorStore

        store = MonitorStore(settings.resolved_db_path)
        m = await store.load_monitor(monitor_id)
        if not m:
            console.print(f"[red]Monitor not found: {monitor_id}[/red]")
            return
        await store.delete_monitor(monitor_id)
        console.print(f"[yellow]Monitor '{m.name}' removed[/yellow]")
    _run_async(_inner())


@monitor_group.command("pause")
@click.argument("monitor_id")
def monitor_pause(monitor_id: str):
    """Pause a monitor"""
    async def _inner():
        from raven.core.monitor.models import MonitorStatus
        from raven.core.monitor.store import MonitorStore

        store = MonitorStore(settings.resolved_db_path)
        m = await store.load_monitor(monitor_id)
        if not m:
            console.print(f"[red]Monitor not found: {monitor_id}[/red]")
            return
        await store.update_status(monitor_id, MonitorStatus.PAUSED)
        console.print(f"[yellow]Monitor '{m.name}' paused[/yellow]")
    _run_async(_inner())


@monitor_group.command("resume")
@click.argument("monitor_id")
def monitor_resume(monitor_id: str):
    """Resume a paused monitor"""
    async def _inner():
        from raven.core.monitor.models import MonitorStatus
        from raven.core.monitor.store import MonitorStore

        store = MonitorStore(settings.resolved_db_path)
        m = await store.load_monitor(monitor_id)
        if not m:
            console.print(f"[red]Monitor not found: {monitor_id}[/red]")
            return
        await store.update_status(monitor_id, MonitorStatus.ACTIVE)
        console.print(f"[green]Monitor '{m.name}' resumed[/green]")
    _run_async(_inner())


@monitor_group.command("logs")
@click.argument("monitor_id")
@click.option("--limit", default=20, type=int, help="Number of checks to show")
def monitor_logs(monitor_id: str, limit: int):
    """Show check history for a monitor"""
    async def _inner():
        from raven.core.monitor.store import MonitorStore

        store = MonitorStore(settings.resolved_db_path)
        m = await store.load_monitor(monitor_id)
        if not m:
            console.print(f"[red]Monitor not found: {monitor_id}[/red]")
            return
        checks = await store.get_checks(monitor_id, limit=limit)
        if not checks:
            console.print("[yellow]No checks recorded yet[/yellow]")
            return
        table = Table(title=f"Check History: {m.name}")
        table.add_column("Time", style="dim")
        table.add_column("Status")
        table.add_column("Response", style="blue")
        table.add_column("Triggered")
        table.add_column("Error", style="red")
        for c in checks:
            t = time.strftime("%H:%M:%S", time.localtime(c.checked_at))
            icon = "[OK]" if c.status == "up" else "[NO]"
            ms = f"{c.response_time_ms:.0f}ms" if c.response_time_ms else ""
            trig = "[!]" if c.triggered else ""
            err = (c.error or "")[:40]
            table.add_row(t, f"{icon} {c.status}", ms, trig, err)
        console.print(table)
    _run_async(_inner())
