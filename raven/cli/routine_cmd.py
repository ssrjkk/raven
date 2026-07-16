from __future__ import annotations

import asyncio
import time

import click
from rich.console import Console
from rich.table import Table

from raven.core.config import settings

console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@click.group(name="routine")
def routine_group():
    """Manage automated routines (briefing, email, file organization)"""


@routine_group.command("list")
@click.option("--user", default=None, help="Filter by user ID")
def routine_list(user: str | None):
    """List configured routines"""
    async def _inner():
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(settings.resolved_db_path)
        routines = await store.list_routines(user_id=user)
        if not routines:
            console.print("[yellow]No routines configured[/yellow]")
            return
        table = Table(title="Routines")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Action", style="blue")
        table.add_column("Schedule", style="green")
        table.add_column("Status")
        table.add_column("Last Run")
        for r in routines:
            icon = {"active": "[OK]", "paused": "[||]", "error": "[ERR]"}.get(r.status.value, "[?]")
            last = r.last_run_status if r.last_run_status else "—"
            table.add_row(r.id[:8], r.name, r.action.value, r.schedule, f"{icon} {r.status.value}", last)
        console.print(table)
    _run_async(_inner())


@routine_group.command("add")
@click.option("--name", required=True, help="Routine name")
@click.option(
    "--action", required=True, type=click.Choice(["send_briefing", "send_message", "check_email", "organize_files"])
)
@click.option("--schedule", default="0 7 * * *", help="Cron expression or HH:MM or interval seconds")
@click.option("--description", default="", help="Description")
@click.option("--user", default="cli", help="User ID")
@click.option("--channel", default="telegram", help="Channel")
def routine_add(name: str, action: str, schedule: str, description: str, user: str, channel: str):
    """Add a new automated routine"""
    async def _inner():
        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger
        from raven.core.routine.store import RoutineStore

        if schedule.replace(":", "").replace("*", "").replace(" ", "").isdigit() and ":" not in schedule:
            trigger = RoutineTrigger.INTERVAL
        else:
            trigger = RoutineTrigger.SCHEDULED

        routine = Routine(
            name=name,
            action=RoutineAction(action),
            trigger=trigger,
            schedule=schedule,
            status=RoutineStatus.ACTIVE,
            user_id=user,
            channel=channel,
        )
        store = RoutineStore(settings.resolved_db_path)
        await store.save_routine(routine)
        console.print(f"[green]Routine '{name}' ({routine.id[:8]}) added[/green]")
        console.print(f"  Action: {action}")
        console.print(f"  Schedule: {schedule}")
        console.print(f"  Trigger: {trigger.value}")
    _run_async(_inner())


@routine_group.command("remove")
@click.argument("routine_id")
def routine_remove(routine_id: str):
    """Remove a routine"""
    async def _inner():
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(settings.resolved_db_path)
        r = await store.load_routine(routine_id)
        if not r:
            console.print(f"[red]Routine not found: {routine_id}[/red]")
            return
        await store.delete_routine(routine_id)
        console.print(f"[yellow]Routine '{r.name}' removed[/yellow]")
    _run_async(_inner())


@routine_group.command("pause")
@click.argument("routine_id")
def routine_pause(routine_id: str):
    """Pause a routine"""
    async def _inner():
        from raven.core.routine.models import RoutineStatus
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(settings.resolved_db_path)
        r = await store.load_routine(routine_id)
        if not r:
            console.print(f"[red]Routine not found: {routine_id}[/red]")
            return
        await store.update_status(routine_id, RoutineStatus.PAUSED)
        console.print(f"[yellow]Routine '{r.name}' paused[/yellow]")
    _run_async(_inner())


@routine_group.command("resume")
@click.argument("routine_id")
def routine_resume(routine_id: str):
    """Resume a paused routine"""
    async def _inner():
        from raven.core.routine.models import RoutineStatus
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(settings.resolved_db_path)
        r = await store.load_routine(routine_id)
        if not r:
            console.print(f"[red]Routine not found: {routine_id}[/red]")
            return
        await store.update_status(routine_id, RoutineStatus.ACTIVE)
        console.print(f"[green]Routine '{r.name}' resumed[/green]")
    _run_async(_inner())


@routine_group.command("logs")
@click.argument("routine_id")
def routine_logs(routine_id: str):
    """Show execution logs for a routine"""
    async def _inner():
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(settings.resolved_db_path)
        logs = await store.get_logs(routine_id)
        if not logs:
            console.print("[yellow]No logs recorded yet[/yellow]")
            return
        table = Table(title="Routine Logs")
        table.add_column("Time", style="dim")
        table.add_column("Status")
        table.add_column("Message", style="white")
        table.add_column("Duration", style="blue")
        for log in logs:
            t = time.strftime("%H:%M:%S", time.localtime(log.created_at))
            icon = "[OK]" if log.status == "success" else "[NO]"
            ms = f"{log.duration_ms:.0f}ms"
            table.add_row(t, f"{icon} {log.status}", log.message[:80], ms)
        console.print(table)
    _run_async(_inner())
