from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import click
import uvicorn
from fastapi import FastAPI

from raven.core.logging import setup_logging
from ravencode.runtime.plugins import ensure_plugin_tools, running_plugin_tools, shutdown_plugins


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Register user plugins on the loop this server will run their tools on, and clean them up.

    `raven aios gateway` is the command README and AGENTS.md tell an operator to run; without this the
    bridge's WebSocket path registered plugins per connection and every HTTP path answered without them.
    """
    await ensure_plugin_tools(watch=True)
    try:
        yield
    finally:
        await shutdown_plugins()


def create_aios_app() -> FastAPI:
    """Build the AI-OS-MVP FastAPI app with security middleware."""
    from raven.core.admin_api import init_auth_routes
    from raven.core.config import settings
    from raven.core.gateway.aios_adapter import get_aios_adapter
    from raven.core.middleware import (
        auth_middleware,
        error_handler_middleware,
        input_sanitize_middleware,
        rate_limit_middleware,
        request_id_middleware,
        security_headers_middleware,
    )
    from raven.core.watermark import install_fastapi_watermark

    app = FastAPI(title="AI-OS-MVP Gateway", lifespan=_lifespan)
    install_fastapi_watermark(app)
    app.middleware("http")(request_id_middleware)
    app.middleware("http")(rate_limit_middleware)
    app.middleware("http")(input_sanitize_middleware)
    app.middleware("http")(auth_middleware)
    app.middleware("http")(error_handler_middleware)
    # Registered last so it is the outermost layer: the gateway binds this app to a port the browser
    # can reach, and headers have to be on the response the error handler produces, not only the ones
    # a route returns itself.
    app.middleware("http")(security_headers_middleware)
    app.include_router(get_aios_adapter().get_bridge_router())
    init_auth_routes(app, str(settings.resolved_db_path))
    return app


@click.group(name="aios")
def aios_group():
    """AI-OS-MVP — Hybrid Web + API + Desktop architecture"""


@aios_group.command()
@click.option("--port", default=3001, help="Fastify AI Gateway port")
def gateway(port: int):
    """Start the AI Gateway (Fastify-compatible bridge)"""
    setup_logging()
    app = create_aios_app()

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
        async with running_plugin_tools():
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
