from __future__ import annotations

import asyncio

import click
import httpx
from rich.console import Console

from raven.core.config import settings

console = Console()


def _headers() -> dict[str, str]:
    """The operator credential, when this install has one.

    Every `flow` subcommand talks to a daemon that answers 401 to an unauthenticated call, so a
    command that skips this header does not list nothing — it fails to ask.
    """
    key = settings.web_secret_key.get_secret_value() if settings.web_secret_key else ""
    return {"X-Raven-Key": key} if key else {}


def _daemon_url(path: str) -> str:
    return f"http://localhost:{settings.ravenflow_port}{path}"


@click.group(name="flow")
def flow_group():
    """RavenFlow — AI workflow orchestrator & gateway"""


@flow_group.command()
@click.option("--port", default=18789, type=int, help="RavenFlow gateway port")
@click.option(
    "--host", default=None, help="Bind address. Defaults to RAVENFLOW_HOST (loopback); 0.0.0.0 needs a firewall."
)
def serve(port: int, host: str | None):
    """Start the RavenFlow gateway daemon"""
    from raven.gateway.daemon import RavenFlowDaemon

    bind = host if host is not None else settings.ravenflow_host
    console.print(f"[bold]RavenFlow Gateway[/bold] starting on {bind}:{port}")
    daemon = RavenFlowDaemon(port=port, host=bind)
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
                _daemon_url("/api/agent"),
                json={"message": message, "channel": channel, "mode": mode, "session_id": session},
                headers=_headers(),
                timeout=120,
            )
            data = resp.json()
            if resp.status_code >= 400:
                console.print(f"[red]Error: HTTP {resp.status_code} {data.get('error', data)}[/red]")
            elif "error" in data:
                console.print(f"[red]Error: {data['error']}[/red]")
            else:
                console.print(data.get("response", ""))

    asyncio.run(_ask())


@flow_group.command(name="sessions")
def flow_sessions():
    """List RavenFlow sessions"""

    async def _list():
        async with httpx.AsyncClient() as client:
            resp = await client.get(_daemon_url("/api/sessions"), headers=_headers(), timeout=10)
            if resp.status_code >= 400:
                console.print(f"[red]Error: HTTP {resp.status_code} {resp.json().get('error', '')}[/red]")
                return
            data = resp.json()
            mgr_sessions = data.get("sessions", [])
            flow_sessions = data.get("flow_sessions", [])
            if mgr_sessions:
                console.print("[bold]Multi-agent sessions:[/bold]")
                for s in mgr_sessions:
                    console.print(
                        f"  {s['id'][:8]} | {s.get('name', '?')} | {s['status']} | msgs: {s['message_count']}"
                    )
            if flow_sessions:
                console.print("[bold]Flow sessions:[/bold]")
                for s in flow_sessions:
                    console.print(f"  {s['id'][:8]} | {s['channel']} | {s['status']} | msgs: {s['messages']}")
            if not mgr_sessions and not flow_sessions:
                console.print("[yellow]No active sessions[/yellow]")

    asyncio.run(_list())
