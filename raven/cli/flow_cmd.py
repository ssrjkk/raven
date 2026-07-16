from __future__ import annotations

import asyncio

import click
import httpx
from rich.console import Console

from raven.core.config import settings

console = Console()


@click.group(name="flow")
def flow_group():
    """RavenFlow — AI workflow orchestrator & gateway"""


@flow_group.command()
@click.option("--port", default=18789, type=int, help="RavenFlow gateway port")
def serve(port: int):
    """Start the RavenFlow gateway daemon"""
    from raven.gateway.daemon import RavenFlowDaemon

    console.print(f"[bold]RavenFlow Gateway[/bold] starting on port {port}")
    daemon = RavenFlowDaemon(port=port)
    asyncio.run(daemon.start())


@flow_group.command(name="ask")
@click.argument("message")
@click.option("--channel", default="cli", help="Source channel")
@click.option("--mode", default="build", help="Agent mode: build, plan, general")
@click.option("--session", default="", help="Session ID")
def flow_ask(message: str, channel: str, mode: str, session: str):
    """Send a message to RavenFlow agent"""
    async def _ask():
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://localhost:{settings.ravenflow_port}/api/agent",
                json={"message": message, "channel": channel, "mode": mode, "session_id": session},
                timeout=120,
            )
            data = resp.json()
            if "error" in data:
                console.print(f"[red]Error: {data['error']}[/red]")
            else:
                console.print(data.get("response", ""))

    asyncio.run(_ask())


@flow_group.command(name="sessions")
def flow_sessions():
    """List RavenFlow sessions"""
    async def _list():
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://localhost:{settings.ravenflow_port}/api/sessions", timeout=10)
            data = resp.json()
            mgr_sessions = data.get("sessions", [])
            flow_sessions = data.get("flow_sessions", [])
            if mgr_sessions:
                console.print("[bold]Multi-agent sessions:[/bold]")
                for s in mgr_sessions:
                    console.print(f"  {s['id'][:8]} | {s.get('name', '?')} | {s['status']} | msgs: {s['message_count']}")
            if flow_sessions:
                console.print("[bold]Flow sessions:[/bold]")
                for s in flow_sessions:
                    console.print(f"  {s['id'][:8]} | {s['channel']} | {s['status']} | msgs: {s['messages']}")
            if not mgr_sessions and not flow_sessions:
                console.print("[yellow]No active sessions[/yellow]")

    asyncio.run(_list())
