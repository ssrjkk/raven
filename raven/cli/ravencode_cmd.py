from __future__ import annotations

import asyncio

import click
from rich.console import Console

from raven.core.gateway.aios_adapter import get_aios_adapter

console = Console()


@click.group(name="ravencode")
def ravencode_group():
    """RavenCode — Autonomous AI engineering framework"""


@ravencode_group.command()
@click.argument("prompt")
@click.option("--task", default="code", help="Task type: code, architecture, fast, debug, refactor")
def ask(prompt: str, task: str):
    """Ask RavenCode AI a question"""

    async def _run():
        result = await get_aios_adapter().ask(prompt, task=task)
        click.echo(f"[{result.provider}/{result.model}]")
        click.echo(result.text)

    asyncio.run(_run())


@ravencode_group.command()
@click.argument("task")
@click.option("--agent", default="autonomous", type=click.Choice(["planner", "coder", "debugger", "autonomous"]))
def agent_run(task: str, agent: str):
    """Run an agent task"""

    async def _run():
        result = await get_aios_adapter().run_agent_task(task, agent)
        if result.success:
            click.echo(f"Agent: {result.agent}")
            click.echo(f"Result: {result.data}")
        else:
            click.echo(f"Error: {result.error}")

    asyncio.run(_run())


@ravencode_group.command()
@click.argument("cmd")
def shell(cmd: str):
    """Execute a shell command"""

    async def _run():
        result = await get_aios_adapter().run_shell(cmd)
        click.echo(result)

    asyncio.run(_run())
