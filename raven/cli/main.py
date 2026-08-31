from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import click
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.cli.aios_cmd import aios_group as _aios
from raven.cli.backup_cmd import backup_group as _backup
from raven.cli.benchmark_cmd import benchmark as _benchmark
from raven.cli.code_cmd import code_group as _code
from raven.cli.db_cmd import db_group as _db
from raven.cli.devices_cmd import devices_group as _devices
from raven.cli.doctor_cmd import doctor as _doctor
from raven.cli.dream_cmd import dream_group as _dream
from raven.cli.flow_cmd import flow_group as _flow
from raven.cli.gateway_runner import _run_gateway, create_gateway
from raven.cli.logs_cmd import logs as _logs
from raven.cli.message_cmd import message_group as _message
from raven.cli.models_cmd import models_group as _models
from raven.cli.monitor_cmd import monitor_group as _monitor
from raven.cli.nodes_cmd import nodes_group as _nodes
from raven.cli.pairing_cmd import pairing_group as _pairing
from raven.cli.plugins_cmd import plugins_group as _plugins
from raven.cli.ravencode_cmd import ravencode_group as _ravencode
from raven.cli.routine_cmd import routine_group as _routine
from raven.cli.security_cmd import security_group as _security
from raven.cli.service_cmd import service_group as _service
from raven.cli.setup_cmd import setup as _setup
from raven.cli.task_cmd import task_group as _task
from raven.cli.upgrade_cmd import upgrade as _upgrade
from raven.cli.voice_cmd import voice as _voice
from raven.core.agent.registry import AgentRegistry
from raven.core.config import settings
from raven.core.db import DatabaseFactory
from raven.core.llm import LLMRouter
from raven.core.logging import setup_logging
from raven.core.plugin_loader import PluginLoader

try:
    import uvloop

    uvloop.install()
except ImportError:
    logger.debug("uvloop not available, using asyncio")

console = Console()


def _run_async(coro):
    return asyncio.run(coro)


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context):
    """Raven AI — Personal AI Assistant 24/7"""
    if ctx.invoked_subcommand is None:
        from raven.cli.coding import code

        code(task="", project=None, agent="raven", max_steps=50, safe=False, plan=False, model=None, parallel=None)


# ── Register extracted command groups ──────────────────────────────

cli.add_command(_aios)
cli.add_command(_backup)
cli.add_command(_benchmark)
cli.add_command(_code)
cli.add_command(_db)
cli.add_command(_devices)
cli.add_command(_dream)
cli.add_command(_flow)
cli.add_command(_message)
cli.add_command(_models)
cli.add_command(_monitor)
cli.add_command(_nodes)
cli.add_command(_pairing)
cli.add_command(_plugins)
cli.add_command(_ravencode)
cli.add_command(_routine)
cli.add_command(_security)
cli.add_command(_service)
cli.add_command(_backup)
cli.add_command(_setup)
cli.add_command(_task)
cli.add_command(_doctor)
cli.add_command(_voice)
cli.add_command(_upgrade)
cli.add_command(_logs)


# ── Core Commands ─────────────────────────────────────────────────


@cli.command()
@click.option("--daemon", is_flag=True, help="Run as daemon process")
@click.option("--port", default=None, type=int, help="Web UI port")
@click.option("--stateless", is_flag=True, default=False, help="Run without memory/context persistence")
@click.option("--ghost", is_flag=True, default=False, help="100% offline mode — local LLM, no external APIs")
def start(daemon: bool, port: int | None, stateless: bool, ghost: bool):
    """Start the Raven AI gateway"""
    setup_logging()
    if daemon:
        console.print("[yellow]Daemon mode requested — use systemd or launchd instead[/yellow]")
        console.print("  systemd: deploy/raven.service")
        console.print("  launchd: sudo cp deploy/com.raven.plist /Library/LaunchDaemons/")
        return

    if ghost:
        from raven.core.config import apply_ghost_mode

        apply_ghost_mode()
        console.print("[dim]Ghost mode: 100% offline, local LLM only[/dim]")

    web_port = port or settings.web_port
    gateway = create_gateway()
    if stateless:
        for agent_conf in gateway.registry._configs.values():
            agent_conf.stateless = True
    title = "[bold blue]Raven AI[/bold blue]"
    try:
        title = "[bold blue]\U0001f426 Raven AI[/bold blue]"
        title.encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        title = "[bold blue]Raven AI[/bold blue]"
    ghost_tag = " [bold yellow]👻 GHOST[/bold yellow]" if ghost else ""
    console.print(
        Panel.fit(
            f"{title}{ghost_tag}\n"
            f"[dim]Web UI: http://localhost:{web_port}[/dim]\n"
            f"[dim]Model: {settings.default_model}[/dim]" + ("\n[dim]Mode: stateless[/dim]" if stateless else "")
        )
    )
    asyncio.run(_run_gateway(gateway, web_port))


@cli.command()
def stop():
    """Stop the Raven AI gateway"""
    import httpx

    try:
        resp = httpx.post(f"http://localhost:{settings.web_port}/api/shutdown", timeout=5)
        if resp.status_code == 200:
            console.print("[green]Raven stopped[/green]")
        else:
            console.print(f"[yellow]Unexpected response: {resp.status_code}[/yellow]")
    except httpx.ConnectError:
        console.print("[yellow]Raven is not running[/yellow]")
    except Exception as e:
        console.print(f"[red]Error stopping: {e}[/red]")


@cli.command()
def status():
    """Show status of all channels and plugins"""

    async def _status():
        db = DatabaseFactory.create()
        await db.connect()
        sessions = await db.get_sessions()
        await db.disconnect()

        import httpx

        api_ok = False
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"http://localhost:{settings.web_port}/api/status")
            api_ok = r.is_success
        except Exception as e:
            logger.debug("Status health check failed: {}", e)

        table = Table(title="Raven AI Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")
        table.add_row("API", "[OK] Running" if api_ok else "[ERR] Stopped", f"port {settings.web_port}")
        table.add_row("Sessions", "[OK]", str(len(sessions)))
        table.add_row("Model", "[--]", settings.default_model)
        table.add_row("DM Policy", "[--]", settings.dm_policy)
        console.print(table)

        if not api_ok:
            raise SystemExit(1)

    asyncio.run(_status())


@cli.command()
def onboard():
    """Interactive setup wizard"""
    from raven.cli.onboard import onboard as _onboard_async

    asyncio.run(_onboard_async())


@cli.command()
@click.option("--template", type=click.Choice(["plugin", "skill"]), help="Scaffold a template instead of full project")
def init(template: str | None):
    """Initialize a new Raven project (scaffold raven.json + .env.example)"""
    if template == "plugin":
        from raven.cli.init_cmd import init_plugin_template

        init_plugin_template()
        return
    if template == "skill":
        from raven.cli.init_cmd import init_skill_template

        init_skill_template()
        return
    from raven.cli.init_cmd import init as _init

    _init()


@cli.command()
def deploy():
    """Generate Docker Compose deployment files"""
    from raven.cli.deploy_cmd import deploy as _deploy

    _deploy()


@cli.command()
@click.option("--dry-run", is_flag=True, help="Check for updates without applying")
def update(dry_run: bool):
    """Check for and apply updates via pip"""
    console.print("[bold]Checking for Raven updates...[/bold]")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--dry-run", "raven-agent"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if "Would install" in result.stdout or "Requirement already satisfied" not in result.stdout:
            console.print(
                "[yellow]Update available[/yellow]" if not dry_run else "[green]Run without --dry-run to update[/green]"
            )
            if not dry_run:
                console.print("[bold]Updating...[/bold]")
                upg = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "raven-agent"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                )
                if upg.returncode == 0:
                    console.print("[green][OK] Update complete![/green]")
                else:
                    console.print(f"[red]Update failed: {upg.stderr}[/red]")
        else:
            console.print("[green]Raven is up to date[/green]")
    except subprocess.TimeoutExpired:
        console.print("[red]Update check timed out[/red]")
    except FileNotFoundError:
        console.print("[yellow]Not installed via pip; update manually[/yellow]")


@cli.command()
@click.argument("task", required=False, default="")
@click.option("--project", "-p", default=None, help="Project root directory")
@click.option("--agent", default="raven", help="Agent type name")
@click.option("--max-steps", default=50, type=int, help="Max agent steps")
@click.option("--safe", is_flag=True, help="Safe mode (confirm dangerous operations)")
@click.option("--plan", is_flag=True, help="Plan-only mode (read-only)")
@click.option("--model", default=None, help="LLM model override")
@click.option("--parallel", "-P", default=None, help="Start a parallel session with this task")
def repl(
    task: str,
    project: str | None,
    agent: str,
    max_steps: int,
    safe: bool,
    plan: bool,
    model: str | None,
    parallel: str | None,
) -> None:
    """Interactive coding agent — like opencode in the terminal"""
    from raven.cli.coding import code as _code

    if not task and not project and not parallel:
        console.print(
            Panel.fit(
                "[bold]Raven Code Agent[/bold]\n\n"
                "Usage:\n"
                "  raven repl                       # interactive REPL\n"
                '  raven repl "fix this bug"        # one-shot + REPL\n'
                "  raven repl -p /path/to/project   # specify project root\n"
                '  raven repl --parallel "task"     # parallel session\n'
                "  raven repl --safe                # safe mode (confirm)\n"
                "  raven repl --plan                # read-only plan mode",
                border_style="cyan",
            )
        )
        return
    _code(task, project, agent, max_steps, safe, plan, model, parallel)


@cli.command()
@click.option("--message", required=True, help="Message to send to agent")
@click.option("--agent", "agent_id", default="default", help="Agent ID to use")
@click.option("--channel", default="cli", help="Channel to simulate")
def agent(message: str, agent_id: str, channel: str):
    """Send a message to the Raven AI agent and get a response"""

    async def _agent():
        db = DatabaseFactory.create()
        await db.connect()
        plugin_loader = PluginLoader()
        plugins_dir = Path(__file__).parent.parent / "plugins"
        for pdir in sorted(plugins_dir.iterdir(), key=lambda d: d.name):
            if pdir.is_dir() and pdir.name != "__pycache__":
                plugin_loader.load_from_dir(pdir)
        from raven.plugins.sessions import plugin as sessions_plugin

        sessions_plugin.init(db)
        llm = LLMRouter()
        registry = AgentRegistry(db, llm, plugin_loader.tools)
        registry.setup_defaults()
        session_id = f"{channel}:agent:{agent_id}"
        session = await db.get_or_create_session(session_id, channel, "agent_user", agent_id)
        agent_obj = registry.create_agent(session, agent_id=agent_id)
        console.print(f"[dim]Agent: {agent_id} | Channel: {channel}[/dim]")
        full = ""
        async for token in agent_obj.run(message):
            full += token
        if full.strip():
            console.print(full)
        await db.disconnect()

    asyncio.run(_agent())


@cli.command()
@click.argument("session_id")
def history(session_id: str):
    """View message history for a session"""

    async def _history():
        db = DatabaseFactory.create()
        await db.connect()
        msgs = await db.get_session_messages(session_id)
        await db.disconnect()
        if not msgs:
            console.print(f"[yellow]No messages in session: {session_id}[/yellow]")
            return
        for m in msgs:
            role_color = {"user": "green", "assistant": "blue", "system": "yellow", "tool": "magenta"}
            color = role_color.get(m.role, "white")
            console.print(f"[{color}][{m.role}][/{color}] {m.content[:200]}")

    asyncio.run(_history())


@cli.command()
def tui():
    """Launch the Textual TUI dashboard"""
    extra_path = Path("D:/PythonPackages")
    if extra_path.is_dir() and str(extra_path) not in sys.path:
        sys.path.insert(0, str(extra_path))
    try:
        from raven.tui.app import run as run_tui
    except ImportError:
        console.print("[red]Textual is not installed. Install with: pip install raven-agent[tui][/red]")
        raise SystemExit(1) from None
    try:
        run_tui()
    except Exception as e:
        console.print(f"[red]TUI error: {e}[/red]")
        raise SystemExit(1) from e


if __name__ == "__main__":
    cli()
