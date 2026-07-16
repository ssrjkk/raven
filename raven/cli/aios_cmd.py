from __future__ import annotations

import asyncio

import click
import uvicorn
from fastapi import FastAPI

from raven.core.logging import setup_logging


@click.group(name="aios")
def aios_group():
    """AI-OS-MVP — Hybrid Web + API + Desktop architecture"""


@aios_group.command()
@click.option("--port", default=3001, help="Fastify AI Gateway port")
def gateway(port: int):
    """Start the AI Gateway (Fastify-compatible bridge)"""
    setup_logging()
    from raven.core.gateway.aios_adapter import get_aios_adapter
    from raven.core.watermark import install_fastapi_watermark

    app = FastAPI(title="AI-OS-MVP Gateway")
    install_fastapi_watermark(app)
    app.include_router(get_aios_adapter().get_bridge_router())

    click.echo(f"AI-OS-MVP Gateway running on http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)


@aios_group.command()
@click.argument("task")
@click.option("--agent", default="autonomous", help="Agent type: planner, coder, debugger, autonomous")
def run(task: str, agent: str):
    """Run an AI-OS-MVP agent task"""
    setup_logging()
    from raven.core.gateway.aios_adapter import get_aios_adapter

    async def _run():
        result = await get_aios_adapter().run_agent(task, agent)
        click.echo(f"Agent: {agent}")
        click.echo(f"Result: {result}")

    asyncio.run(_run())


@aios_group.command()
@click.argument("cmd")
def run_command(cmd: str):
    """Execute a command via the unified runtime"""
    from raven.core.gateway.aios_adapter import get_aios_adapter

    async def _run():
        result = await get_aios_adapter().run_command(cmd)
        click.echo(result)

    asyncio.run(_run())
