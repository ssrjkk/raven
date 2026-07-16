from __future__ import annotations

import asyncio
import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.core.config import settings

console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@click.group(name="task")
def task_group():
    """Manage and run tasks"""


@task_group.command("list")
@click.option("--user", default=None, help="Filter by user ID")
@click.option("--status", default=None, help="Filter by status (pending/running/completed/failed/cancelled)")
@click.option("--limit", default=20, type=int, help="Max results")
def task_list(user: str | None, status: str | None, limit: int):
    """List tasks"""
    async def _inner():
        from raven.core.task_engine.store import TaskStore

        store = TaskStore(settings.resolved_db_path)
        tasks = await store.list_tasks(user_id=user, status=status, limit=limit)
        if not tasks:
            console.print("[yellow]No tasks found[/yellow]")
            return
        table = Table(title="Tasks")
        table.add_column("ID", style="cyan")
        table.add_column("Goal", style="white")
        table.add_column("Status", style="green")
        table.add_column("Steps", style="blue")
        table.add_column("Created")
        for t in tasks:
            status_icon = {
                "pending": "[..]",
                "running": "[..]",
                "completed": "[OK]",
                "failed": "[NO]",
                "cancelled": "[!]",
                "paused": "[||]",
            }
            icon = status_icon.get(t.status.value, "[?]")
            done = sum(1 for s in t.steps if s.status.value == "completed")
            total = len(t.steps)
            created = time.strftime("%H:%M", time.localtime(t.created_at))
            table.add_row(t.id[:8], t.goal[:60], f"{icon} {t.status.value}", f"{done}/{total}", created)
        console.print(table)
    _run_async(_inner())


@task_group.command("show")
@click.argument("task_id")
def task_show(task_id: str):
    """Show detailed task info"""
    async def _inner():
        from raven.core.task_engine.store import TaskStore

        store = TaskStore(settings.resolved_db_path)
        t = await store.load_task(task_id)
        if not t:
            console.print(f"[red]Task not found: {task_id}[/red]")
            return
        console.print(
            Panel.fit(
                f"[bold]Task: {t.id}[/bold]\n"
                f"[cyan]Goal:[/cyan] {t.goal}\n"
                f"[cyan]Status:[/cyan] {t.status.value}\n"
                f"[cyan]Steps:[/cyan] {len(t.steps)}\n"
                f"[cyan]Created:[/cyan] {time.ctime(t.created_at)}"
            )
        )
        for i, step in enumerate(t.steps):
            icon = {"pending": "[..]", "running": "[..]", "completed": "[OK]", "failed": "[NO]", "cancelled": "[!]"}.get(
                step.status.value, "[?]"
            )
            console.print(f"  {icon} Step {i + 1}: {step.description} [dim]({step.tool})[/dim]")
            if step.error:
                console.print(f"     [red]Error: {step.error}[/red]")
    _run_async(_inner())


@task_group.command("run")
@click.argument("goal")
@click.option("--user", default="cli", help="User ID")
@click.option("--channel", default="cli", help="Channel")
def task_run(goal: str, user: str, channel: str):
    """Plan and execute a goal as a task"""
    from raven.core.llm import LLMRouter
    from raven.core.task_engine.planner import TaskPlanner
    from raven.core.task_engine.runner import TaskRunner
    from raven.core.task_engine.store import TaskStore
    from raven.tools.register_all import create_tool_registry

    async def _run():
        tools = create_tool_registry()
        llm = LLMRouter()
        store = TaskStore(settings.resolved_db_path)
        planner = TaskPlanner(tools)
        runner = TaskRunner(store, tools)

        with console.status("[bold]Planning...", spinner="dots"):
            task = await planner.plan(goal, llm, user_id=user, channel=channel)

        if not task.steps:
            console.print("[red]Planner returned no steps. LLM response parsing may have failed.[/red]")
            return

        console.print(f"[green]Plan:[/green] {task.plan_summary or goal}")
        for i, step in enumerate(task.steps):
            console.print(f"  {i + 1}. {step.description} [dim]({step.tool})[/dim]")

        await runner.submit(task)
        console.print(f"[green]Task {task.id[:8]} submitted, running...[/green]")

        task = await runner.wait(task.id, timeout=300)
        if task.status.value == "completed":
            console.print("[green][OK] Task completed![/green]")
        elif task.status.value == "failed":
            console.print(f"[red][NO] Task failed: {task.error}[/red]")
        elif task.status.value == "cancelled":
            console.print("[yellow][!] Task cancelled[/yellow]")
        else:
            console.print(f"[yellow]Task status: {task.status.value}[/yellow]")

    asyncio.run(_run())


@task_group.command("cancel")
@click.argument("task_id")
def task_cancel(task_id: str):
    """Cancel a running task"""
    from raven.core.task_engine.runner import TaskRunner
    from raven.core.task_engine.store import TaskStore
    from raven.tools.register_all import create_tool_registry

    async def _cancel():
        tools = create_tool_registry()
        store = TaskStore(settings.resolved_db_path)
        runner = TaskRunner(store, tools)
        ok = await runner.cancel(task_id)
        if ok:
            console.print(f"[yellow]Task {task_id[:8]} cancelled[/yellow]")
        else:
            console.print(f"[red]Task not found or already finished: {task_id}[/red]")

    asyncio.run(_cancel())


@task_group.command("retry")
@click.argument("task_id")
def task_retry(task_id: str):
    """Retry a failed task"""
    async def _retry():
        from raven.core.task_engine.models import TaskStatus
        from raven.core.task_engine.runner import TaskRunner
        from raven.core.task_engine.store import TaskStore
        from raven.tools.register_all import create_tool_registry

        tools = create_tool_registry()
        store = TaskStore(settings.resolved_db_path)
        runner = TaskRunner(store, tools)
        task = await store.load_task(task_id)
        if not task:
            console.print(f"[red]Task not found: {task_id}[/red]")
            return
        task.status = TaskStatus.PENDING
        task.error = None
        task.current_step_index = 0
        for step in task.steps:
            step.status = TaskStatus.PENDING
            step.error = None
        await store.save_task(task)
        await runner.submit(task)
        console.print(f"[green]Task {task_id[:8]} retry submitted[/green]")

    _run_async(_retry())


@task_group.command("logs")
@click.argument("task_id")
def task_logs(task_id: str):
    """Show step details for a task"""
    async def _inner():
        from raven.core.task_engine.store import TaskStore

        store = TaskStore(settings.resolved_db_path)
        t = await store.load_task(task_id)
        if not t:
            console.print(f"[red]Task not found: {task_id}[/red]")
            return
        for step in t.steps:
            console.print(f"\n[bold]Step {step.order + 1}:[/bold] {step.description}")
            console.print(f"  Tool: [cyan]{step.tool}[/cyan]")
            console.print(f"  Status: {step.status.value}")
            if step.result:
                result_str = str(step.result)[:300]
                console.print(f"  Result: {result_str}")
            if step.error:
                console.print(f"  [red]Error: {step.error}[/red]")
    _run_async(_inner())
