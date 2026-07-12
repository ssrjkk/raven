from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

from loguru import logger

try:
    import uvloop

    uvloop.install()
except ImportError:
    logger.debug("uvloop not available, using asyncio")

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.cli.gateway_runner import _run_gateway, create_gateway
from raven.core.agent.registry import AgentRegistry
from raven.core.config import settings
from raven.core.config_store import config_store
from raven.core.db import DatabaseFactory
from raven.core.gateway.aios_adapter import get_aios_adapter
from raven.core.llm import LLMRouter
from raven.core.logging import setup_logging
from raven.core.models import Message
from raven.core.plugin_loader import PluginLoader

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context):
    """Raven AI — Personal AI Assistant 24/7"""
    if ctx.invoked_subcommand is None:
        from raven.cli.coding import code
        code(task="", project=None, agent="raven", max_steps=50, safe=False, plan=False, model=None, parallel=None)


# ── AI-OS-MVP (Hybrid Architecture) ──────────────────────────────


@cli.group()
def aios():
    """AI-OS-MVP — Hybrid Web + API + Desktop architecture"""


@aios.command()
@click.option("--port", default=3001, help="Fastify AI Gateway port")
def gateway(port: int):
    """Start the AI Gateway (Fastify-compatible bridge)"""
    setup_logging()
    import uvicorn
    from fastapi import FastAPI

    from raven.core.watermark import install_fastapi_watermark

    app = FastAPI(title="AI-OS-MVP Gateway")
    install_fastapi_watermark(app)
    app.include_router(get_aios_adapter().get_bridge_router())

    click.echo(f"AI-OS-MVP Gateway running on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)  # noqa: S104


@aios.command()
@click.argument("task")
@click.option("--agent", default="autonomous", help="Agent type: planner, coder, debugger, autonomous")
def run(task: str, agent: str):
    """Run an AI-OS-MVP agent task"""
    setup_logging()
    import asyncio

    async def _run():
        result = await get_aios_adapter().run_agent(task, agent)
        click.echo(f"Agent: {agent}")
        click.echo(f"Result: {result}")

    asyncio.run(_run())


@aios.command()
@click.argument("cmd")
def exec(cmd: str):
    """Execute a command via the unified runtime"""
    import asyncio

    async def _run():
        result = await get_aios_adapter().run_command(cmd)
        click.echo(result)

    asyncio.run(_run())


# ── RavenCode (High-Level API) ────────────────────────────────────


@cli.group()
def ravencode():
    """RavenCode — Autonomous AI engineering framework"""


@ravencode.command()
@click.argument("prompt")
@click.option("--task", default="code", help="Task type: code, architecture, fast, debug, refactor")
def ask(prompt: str, task: str):
    """Ask RavenCode AI a question"""
    import asyncio

    async def _run():
        result = await get_aios_adapter().ask(prompt, task=task)
        click.echo(f"[{result.provider}/{result.model}]")
        click.echo(result.text)

    asyncio.run(_run())


@ravencode.command()
@click.argument("task")
@click.option("--agent", default="autonomous", type=click.Choice(["planner", "coder", "debugger", "autonomous"]))
def agent_run(task: str, agent: str):
    """Run an agent task"""
    import asyncio

    async def _run():
        result = await get_aios_adapter().run_agent_task(task, agent)
        if result.success:
            click.echo(f"Agent: {result.agent}")
            click.echo(f"Result: {result.data}")
        else:
            click.echo(f"Error: {result.error}")

    asyncio.run(_run())


@ravencode.command()
@click.argument("cmd")
def shell(cmd: str):
    """Execute a shell command"""
    import asyncio

    async def _run():
        result = await get_aios_adapter().run_shell(cmd)
        click.echo(result)

    asyncio.run(_run())


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
            r = httpx.get(f"http://localhost:{settings.web_port}/api/status", timeout=3)
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
def doctor():
    """Diagnose configuration, dependencies, and service health"""
    console.print(Panel.fit("[bold]Raven AI Doctor[/bold]"))
    checks = []

    config_store.load()
    cfg = config_store._data

    checks.append(("Config Store", f"[OK] {config_store.path}" if config_store.path.exists() else "[!]️  Not initialized"))
    checks.append(("Python", sys.version))
    checks.append(("DB Path", str(settings.resolved_db_path)))

    has_any_key = bool(
        cfg.get("openrouter_api_key")
        or cfg.get("anthropic_api_key")
        or cfg.get("openai_api_key")
        or cfg.get("ollama_base_url")
    )
    checks.append(("LLM Provider", "[OK] Configured" if has_any_key else "[!]️  No provider configured"))

    provider_names = []
    if cfg.get("openrouter_api_key"):
        provider_names.append("OpenRouter")
    if cfg.get("anthropic_api_key"):
        provider_names.append("Anthropic")
    if cfg.get("openai_api_key"):
        provider_names.append("OpenAI")
    if cfg.get("ollama_base_url"):
        provider_names.append("Ollama")
    if provider_names:
        checks.append(("Providers", ", ".join(provider_names)))

    checks.append(("Default Model", cfg.get("default_model", "—")))
    checks.append(("Telegram", "[OK] Configured" if cfg.get("telegram_bot_token") else "[!]️  Not set"))
    checks.append(("Discord", "[OK] Configured" if cfg.get("discord_bot_token") else "[!]️  Not set"))
    checks.append(("Slack", "[OK] Configured" if cfg.get("slack_bot_token") else "[!]️  Not set"))
    checks.append(("DM Policy", cfg.get("dm_policy", "pairing")))
    checks.append(("Web Port", str(cfg.get("web_port", 18888))))
    checks.append(("Web Secret Key", "[OK] Set" if cfg.get("web_secret_key") else "[!]️  Not set"))

    import importlib.util
    has_crypto = importlib.util.find_spec("cryptography")
    checks.append(("Secrets Encryption", "[OK] Available" if has_crypto else "[!]️  Install cryptography for secrets"))

    try:
        import win32serviceutil  # noqa: F401

        checks.append(("Windows Service", "[OK] pywin32 available"))
    except ImportError:
        if sys.platform == "win32":
            checks.append(("Windows Service", "[!]️  Install pywin32 for service support"))

    try:
        import playwright  # noqa: F401

        checks.append(("Playwright", "[OK] Installed"))
    except ImportError:
        checks.append(("Playwright", "[!]️  Not installed (browser plugin limited)"))

    api_ok = False
    try:
        import httpx

        r = httpx.get(f"http://localhost:{settings.web_port}/api/status", timeout=3)
        api_ok = r.is_success
    except Exception as e:
        logger.debug("Doctor health check failed: {}", e)
    checks.append(("API", "[OK] Running" if api_ok else "[ERR] Stopped"))

    mcp_raw = settings.mcp_servers
    if mcp_raw:
        try:
            mcp_servers = json.loads(mcp_raw)
            mcp_status = f"{len(mcp_servers)} configured"
        except json.JSONDecodeError:
            mcp_status = "[!] Invalid JSON"
        checks.append(("MCP Servers", mcp_status))

    sb_policy = settings.channel_sandbox_policy
    if sb_policy:
        sb_status = "[OK] Configured"
        try:
            json.loads(sb_policy)
        except json.JSONDecodeError:
            sb_status = "[!] Invalid JSON"
        checks.append(("Channel Sandbox Policy", sb_status))

    table = Table(show_header=False)
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    for name, result in checks:
        table.add_row(name, result)
    console.print(table)

    if not api_ok and not any(key in os.environ.get("RUNNING_TESTS", "") for key in ("1", "true")):
        console.print("\n[yellow]Raven is not running. Start it with: raven start[/yellow]")


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


@cli.group()
def security():
    """Security audit and policy management"""


@security.command("audit")
@click.option("--deep", is_flag=True, help="Run deep audit (network, env file, dependencies)")
@click.option("--fix", is_flag=True, help="Auto-fix common issues")
def security_audit(deep: bool, fix: bool):
    """Run comprehensive security audit checks"""
    from raven.cli.doctor import _render_security_audit
    from raven.core.security.security_audit import SecurityAudit

    auditor = SecurityAudit()
    results = auditor.run_all(deep=deep)
    _render_security_audit(results, fix=fix)


@cli.group()
def service():
    """Manage Raven as a platform-native service"""


@service.command("install")
def service_install():
    """Install Raven as a service (Windows/Systemd/Launchd)"""
    from raven.cli.service import service_install as _install

    _install()


@service.command("start")
def service_start():
    """Start the Raven service"""
    from raven.cli.service import service_start as _start

    _start()


@service.command("stop")
def service_stop():
    """Stop the Raven service"""
    from raven.cli.service import service_stop as _stop

    _stop()


@service.command("status")
def service_status():
    """Show Raven service status"""
    from raven.cli.service import service_status as _status

    _status()


@service.command("remove")
def service_remove():
    """Remove the Raven service"""
    from raven.cli.service import service_remove as _remove

    _remove()


@service.command("restart")
def service_restart():
    """Restart the Raven service"""
    from raven.cli.service import service_restart as _restart

    _restart()


@cli.command()
@click.option("--dry-run", is_flag=True, help="Check for updates without applying")
def update(dry_run: bool):
    """Check for and apply updates via pip"""
    import subprocess

    console.print("[bold]Checking for Raven updates...[/bold]")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "--dry-run", "raven-agent"],
            capture_output=True,
            text=True,
            timeout=30,
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
                    timeout=120,
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


@cli.group()
def pairing():
    """Manage user pairing"""


@pairing.command("list")
def pairing_list():
    """List pending pairing requests"""

    async def _list():
        db = DatabaseFactory.create()
        await db.connect()
        users = await db.get_pending_pairing_users()
        await db.disconnect()
        if not users:
            console.print("[yellow]No pending pairing requests[/yellow]")
            return
        table = Table(title="Pending Pairing Requests")
        table.add_column("User ID", style="cyan")
        table.add_column("Channel")
        table.add_column("Pairing Code", style="yellow")
        for u in users:
            table.add_row(u["id"], u["channel"], u.get("pairing_code", ""))
        console.print(table)

    asyncio.run(_list())


@pairing.command("approve")
@click.argument("code")
def pairing_approve(code: str):
    """Approve a user by pairing code"""

    async def _approve():
        db = DatabaseFactory.create()
        await db.connect()
        user = await db.get_user_by_pairing_code(code)
        if not user:
            console.print(f"[red]No user found with pairing code: {code}[/red]")
            await db.disconnect()
            return
        await db.set_user_allowed(user["id"], True)
        await db.set_pairing_code(user["id"], "")
        console.print(f"[green]User {user['id']} approved![/green]")
        await db.disconnect()

    asyncio.run(_approve())


@cli.group()
def message():
    """Send messages via channels"""


@message.command("send")
@click.option(
    "--channel",
    required=True,
    help="Target channel (telegram, discord, webchat, slack, whatsapp, matrix, googlechat, signal, irc, teams, feishu, line)",
)
@click.option("--user", required=True, help="User ID")
@click.option("--text", required=True, help="Message text")
@click.option("--session", default=None, help="Session ID (optional)")
def msg_send(channel: str, user: str, text: str, session: str | None):
    """Send a message to a user via Raven AI"""

    async def _send():
        db = DatabaseFactory.create()
        await db.connect()

        session_id = session or f"{channel}:{user}:cli"
        sess = await db.get_or_create_session(session_id, channel, user)

        plugin_loader = PluginLoader()
        plugins_dir = Path(__file__).parent.parent / "plugins"
        for pdir in plugins_dir.iterdir():
            if pdir.is_dir() and pdir.name != "__pycache__":
                plugin_loader.load_from_dir(pdir)

        llm = LLMRouter()
        registry = AgentRegistry(db, llm, plugin_loader.tools)
        registry.setup_defaults()
        agent = registry.create_agent(sess)

        user_msg = Message(session_id=session_id, channel=channel, role="user", content=text)
        await db.save_message(user_msg)

        console.print(f"[dim]Sending to {channel}/{user}...[/dim]")
        full = ""
        async for token in agent.run(text):
            full += token

        if full.strip():
            assistant_msg = Message(session_id=session_id, channel=channel, role="assistant", content=full)
            await db.save_message(assistant_msg)
            console.print(f"[green]Response:[/green] {full[:500]}")

        await db.disconnect()

    asyncio.run(_send())


@cli.group()
def models():
    """List available models"""


@models.command("list")
def models_list():
    """List configured LLM models"""
    table = Table(title="Configured Models")
    table.add_column("Provider", style="cyan")
    table.add_column("Status")
    table.add_column("Default")
    table.add_row(
        "OpenRouter",
        "[OK]" if settings.openrouter_api_key else "[NO]",
        "✓" if settings.default_model.startswith("openrouter/") else "",
    )
    table.add_row(
        "Anthropic",
        "[OK]" if settings.anthropic_api_key else "[NO]",
        "✓" if settings.default_model.startswith("claude") else "",
    )
    table.add_row("OpenAI", "[OK]" if settings.openai_api_key else "[NO]", "")
    table.add_row(
        "Ollama",
        "[OK]" if settings.ollama_base_url else "[NO]",
        "✓" if settings.default_model.startswith("ollama/") else "",
    )
    console.print(table)
    console.print(f"\nDefault model: [bold]{settings.default_model}[/bold]")


@cli.group()
def plugins():
    """Manage plugins"""


@plugins.command("list")
def plugins_list():
    """List loaded plugins"""
    gateway = create_gateway()
    plugins_dir = Path(__file__).parent.parent / "plugins"
    loader = gateway.plugin_loader
    for pdir in plugins_dir.iterdir():
        if pdir.is_dir() and pdir.name != "__pycache__":
            loader.load_from_dir(pdir)
    table = Table(title="Loaded Plugins")
    table.add_column("Plugin", style="cyan")
    table.add_column("Tools")
    for pdir in sorted(plugins_dir.iterdir(), key=lambda d: d.name):
        if pdir.is_dir() and pdir.name != "__pycache__":
            tools_in_plugin = [t for t in loader.tools if t.handler.__module__.startswith(f"raven.plugins.{pdir.name}")]
            if tools_in_plugin:
                table.add_row(pdir.name, ", ".join(t.name for t in tools_in_plugin))
    if not loader.tools:
        table.add_row("(none)", "No plugins loaded")
    console.print(table)


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


@cli.group()
def db():
    """Manage the database"""


@db.command("migrate")
@click.option("--target", default=None, type=int, help="Target migration version")
def db_migrate(target: int | None):
    """Run pending database migrations"""

    async def _migrate():
        db = DatabaseFactory.create()
        await db.connect()
        await db.disconnect()
        console.print("[green]Migrations complete[/green]")

    asyncio.run(_migrate())


@db.command("backup")
@click.argument("output", default=None, required=False)
def db_backup(output: str | None):
    """Backup the database"""
    import shutil

    src = settings.resolved_db_path
    if not src.exists():
        console.print("[red]Database file not found[/red]")
        return
    dst = Path(output) if output else src.with_suffix(f".backup.{src.suffix}")
    shutil.copy2(str(src), str(dst))
    console.print(f"[green]Database backed up to {dst}[/green]")


@db.command("version")
def db_version():
    """Show current database schema version"""

    async def _version():
        db = DatabaseFactory.create()
        await db.connect()
        version = await db.migrator.get_current_version()
        await db.disconnect()
        console.print(f"Database schema version: [bold]{version}[/bold]")

    asyncio.run(_version())


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
        for pdir in plugins_dir.iterdir():
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


@cli.group()
def task():
    """Manage and run tasks"""


@task.command("list")
@click.option("--user", default=None, help="Filter by user ID")
@click.option("--status", default=None, help="Filter by status (pending/running/completed/failed/cancelled)")
@click.option("--limit", default=20, type=int, help="Max results")
def task_list(user: str | None, status: str | None, limit: int):
    """List tasks"""
    from raven.core.task_engine.store import TaskStore

    store = TaskStore(settings.resolved_db_path)
    tasks = store.list_tasks(user_id=user, status=status, limit=limit)
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


@task.command("show")
@click.argument("task_id")
def task_show(task_id: str):
    """Show detailed task info"""
    from raven.core.task_engine.store import TaskStore

    store = TaskStore(settings.resolved_db_path)
    t = store.load_task(task_id)
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


@task.command("run")
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


@task.command("cancel")
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


@task.command("retry")
@click.argument("task_id")
def task_retry(task_id: str):
    """Retry a failed task"""
    from raven.core.task_engine.runner import TaskRunner
    from raven.core.task_engine.store import TaskStore
    from raven.tools.register_all import create_tool_registry

    async def _retry():
        tools = create_tool_registry()
        store = TaskStore(settings.resolved_db_path)
        runner = TaskRunner(store, tools)
        task = store.load_task(task_id)
        if not task:
            console.print(f"[red]Task not found: {task_id}[/red]")
            return
        from raven.core.task_engine.models import TaskStatus
        task.status = TaskStatus.PENDING
        task.error = None
        task.current_step_index = 0
        for step in task.steps:
            step.status = TaskStatus.PENDING
            step.error = None
        store.save_task(task)
        await runner.submit(task)
        console.print(f"[green]Task {task_id[:8]} retry submitted[/green]")

    asyncio.run(_retry())


@task.command("logs")
@click.argument("task_id")
def task_logs(task_id: str):
    """Show step details for a task"""
    from raven.core.task_engine.store import TaskStore

    store = TaskStore(settings.resolved_db_path)
    t = store.load_task(task_id)
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


@cli.group()
def monitor():
    """Manage monitors (HTTP, price, RSS, file, process)"""


@monitor.command("list")
@click.option("--user", default=None, help="Filter by user ID")
@click.option("--status", default=None, help="Filter by status (active/paused)")
def monitor_list(user: str | None, status: str | None):
    """List all monitors"""
    from raven.core.monitor.store import MonitorStore

    store = MonitorStore(settings.resolved_db_path)
    monitors = store.list_monitors(user_id=user, status=status)
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


@monitor.command("add")
@click.option("--name", required=True, help="Monitor name")
@click.option("--type", "mon_type", required=True, type=click.Choice(["http", "price", "rss", "file", "process"]))
@click.option("--target", required=True, help="URL, symbol, path, or process name")
@click.option("--interval", default=300, type=int, help="Check interval in seconds")
@click.option("--condition", "conditions", multiple=True, help="Condition (e.g. status_code!=200)")
@click.option("--user", default="cli", help="User ID")
def monitor_add(name: str, mon_type: str, target: str, interval: int, conditions: tuple[str], user: str):
    """Add a new monitor"""
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
    store.save_monitor(monitor)
    console.print(f"[green]Monitor '{name}' ({monitor.id[:8]}) added[/green]")
    if parsed_conditions:
        for cond in parsed_conditions:
            console.print(f"  [!] Condition: {cond.metric} {cond.operator.value} {cond.value}")


@monitor.command("remove")
@click.argument("monitor_id")
def monitor_remove(monitor_id: str):
    """Remove a monitor"""
    from raven.core.monitor.store import MonitorStore

    store = MonitorStore(settings.resolved_db_path)
    m = store.load_monitor(monitor_id)
    if not m:
        console.print(f"[red]Monitor not found: {monitor_id}[/red]")
        return
    store.delete_monitor(monitor_id)
    console.print(f"[yellow]Monitor '{m.name}' removed[/yellow]")


@monitor.command("pause")
@click.argument("monitor_id")
def monitor_pause(monitor_id: str):
    """Pause a monitor"""
    from raven.core.monitor.models import MonitorStatus
    from raven.core.monitor.store import MonitorStore

    store = MonitorStore(settings.resolved_db_path)
    m = store.load_monitor(monitor_id)
    if not m:
        console.print(f"[red]Monitor not found: {monitor_id}[/red]")
        return
    store.update_status(monitor_id, MonitorStatus.PAUSED)
    console.print(f"[yellow]Monitor '{m.name}' paused[/yellow]")


@monitor.command("resume")
@click.argument("monitor_id")
def monitor_resume(monitor_id: str):
    """Resume a paused monitor"""
    from raven.core.monitor.models import MonitorStatus
    from raven.core.monitor.store import MonitorStore

    store = MonitorStore(settings.resolved_db_path)
    m = store.load_monitor(monitor_id)
    if not m:
        console.print(f"[red]Monitor not found: {monitor_id}[/red]")
        return
    store.update_status(monitor_id, MonitorStatus.ACTIVE)
    console.print(f"[green]Monitor '{m.name}' resumed[/green]")


@monitor.command("logs")
@click.argument("monitor_id")
@click.option("--limit", default=20, type=int, help="Number of checks to show")
def monitor_logs(monitor_id: str, limit: int):
    """Show check history for a monitor"""
    from raven.core.monitor.store import MonitorStore

    store = MonitorStore(settings.resolved_db_path)
    m = store.load_monitor(monitor_id)
    if not m:
        console.print(f"[red]Monitor not found: {monitor_id}[/red]")
        return
    checks = store.get_checks(monitor_id, limit=limit)
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


@cli.group()
def code():
    """Coding assistant — index, review, sessions"""


@code.command("index")
@click.argument("path", default=".", required=False)
@click.option("--max-files", default=2000, type=int, help="Max files to index")
def code_index(path: str, max_files: int):
    """Index a codebase for context-aware assistance"""
    from pathlib import Path

    from raven.core.coder.indexer import CodeIndexer

    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        console.print(f"[red]Not a directory: {p}[/red]")
        return
    with console.status("[bold]Indexing...", spinner="dots"):
        indexer = CodeIndexer(str(p))
        indexer.index(max_files=max_files)
    summary = indexer.summary()
    console.print(f"[green]Indexed {summary['files']} files[/green]")
    for lang, count in summary.get("languages", {}).items():
        console.print(f"  {lang}: {count} files")


@code.command("search")
@click.argument("query")
@click.argument("path", default=".", required=False)
def code_search(query: str, path: str):
    """Search indexed codebase for symbols"""
    from pathlib import Path

    from raven.core.coder.indexer import CodeIndexer

    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        p = Path.cwd()
    with console.status("[bold]Searching...", spinner="dots"):
        indexer = CodeIndexer(str(p))
        indexer.index(max_files=2000)
        results = indexer.search(query)

    if not results:
        console.print("[yellow]No results found[/yellow]")
        return
    table = Table(title=f"Search: {query}")
    table.add_column("File", style="cyan")
    table.add_column("Language", style="blue")
    table.add_column("Symbols", style="green")
    for f in results[:20]:
        syms = ", ".join(s.name for s in f.symbols[:5])
        table.add_row(f.path, f.language, syms)
    console.print(table)


@code.command("review")
@click.argument("path")
@click.option("--language", default="", help="Programming language")
def code_review(path: str, language: str):
    """Review a file for issues"""
    from pathlib import Path

    from raven.core.coder.review import CodeReviewer

    p = Path(path).expanduser().resolve()
    if not p.is_file():
        console.print(f"[red]File not found: {p}[/red]")
        return
    content = p.read_text(encoding="utf-8", errors="replace")
    ext = p.suffix
    lang_map = {".py": "python", ".js": "javascript", ".ts": "typescript", ".go": "go", ".rs": "rust", ".java": "java"}
    lang = language or lang_map.get(ext, "")

    reviewer = CodeReviewer()
    comments = asyncio.run(reviewer.review_file(str(p), content, lang))

    if not comments:
        console.print("[green]No issues found![/green]")
        return

    table = Table(title=f"Review: {p.name}")
    table.add_column("Line", style="cyan")
    table.add_column("Severity")
    table.add_column("Issue", style="white")
    table.add_column("Suggestion", style="dim")
    for c in comments:
        severity_colors = {"critical": "red", "warning": "yellow", "suggestion": "blue", "praise": "green"}
        table.add_row(
            str(c.line),
            f"[{severity_colors.get(c.severity.value, 'white')}]{c.severity.value}[/]",
            c.message,
            c.suggestion,
        )
    console.print(table)


@code.command("start")
@click.argument("goal")
@click.option("--project", default=".", help="Project path")
@click.option("--user", default="cli", help="User ID")
def code_start(goal: str, project: str, user: str):
    """Start a coding session"""
    from pathlib import Path

    from raven.core.coder.models import CodingSession
    from raven.core.coder.session import CodingSessionManager

    p = Path(project).expanduser().resolve()
    session = CodingSession(user_id=user, goal=goal, project_path=str(p))
    mgr = CodingSessionManager(settings.resolved_db_path)
    mgr.create_session(session)
    console.print(f"[green]Coding session started: {session.id[:8]}[/green]")
    console.print(f"  Goal: {goal}")
    console.print(f"  Project: {p}")
    console.print(f"  [dim]Run 'raven code status {session.id[:8]}' to check[/dim]")


@code.command("status")
@click.argument("session_id")
def code_status(session_id: str):
    """Show coding session status"""
    from raven.core.coder.session import CodingSessionManager

    mgr = CodingSessionManager(settings.resolved_db_path)
    session = mgr.get_session(session_id)
    if not session:
        console.print(f"[red]Session not found: {session_id}[/red]")
        return
    console.print(
        Panel.fit(
            f"[bold]Coding Session: {session.id}[/bold]\n"
            f"[cyan]Goal:[/cyan] {session.goal}\n"
            f"[cyan]Project:[/cyan] {session.project_path}\n"
            f"[cyan]Status:[/cyan] {session.status.value}\n"
            f"[cyan]Files:[/cyan] {len(session.files)}\n"
            f"[cyan]Messages:[/cyan] {len(session.history)}"
        )
    )


@code.command("end")
@click.argument("session_id")
def code_end(session_id: str):
    """End a coding session"""
    from raven.core.coder.models import SessionStatus
    from raven.core.coder.session import CodingSessionManager

    mgr = CodingSessionManager(settings.resolved_db_path)
    session = mgr.get_session(session_id)
    if not session:
        console.print(f"[red]Session not found: {session_id}[/red]")
        return
    session.status = SessionStatus.COMPLETED
    mgr.update_session(session)
    console.print(f"[green]Session {session_id[:8]} ended[/green]")


@code.command("analyze")
@click.argument("path", default=".", required=False)
@click.option("--all", "show_all", is_flag=True, help="Show all lines including unannotated")
def code_analyze(path: str, show_all: bool):
    """Analyze codebase structure — dependencies, call graph, symbols"""
    from pathlib import Path

    from rich.panel import Panel

    from raven.core.coder.analyzer import CodeAnalyzer

    p = Path(path).expanduser().resolve()
    analyzer = CodeAnalyzer(str(p.parent if p.is_file() else p))
    if p.is_file():
        result = analyzer.explain_file(p)
        console.print(result.summary)
        if result.symbols:
            console.print(Panel.fit(
                "\n".join(f"  {s.name} ({s.kind}, line {s.line})" + (f" — {s.docstring[:50]}" if s.docstring else "")
                          for s in result.symbols),
                title="Symbols",
            ))
        if result.call_graph:
            table = Table(title="Call Graph")
            table.add_column("Caller", style="cyan")
            table.add_column("Callee", style="green")
            table.add_column("Line", style="dim")
            for caller, callee, line in sorted(result.call_graph, key=lambda x: x[2]):
                table.add_row(caller, callee, str(line))
            console.print(table)
    else:
        results = analyzer.analyze(p)
        console.print(analyzer.format_analysis(results))


@code.command("explain")
@click.argument("path")
@click.option("--all", "show_all", is_flag=True, help="Show every line")
@click.option("--function", "-f", "func_name", default="", help="Trace a specific function")
def code_explain(path: str, show_all: bool, func_name: str):
    """Explain code line-by-line with annotations and origin info"""
    from pathlib import Path

    from rich.table import Table

    from raven.core.coder.analyzer import CodeAnalyzer

    p = Path(path).expanduser().resolve()
    if not p.exists():
        console.print(f"[red]File not found: {p}[/red]")
        return
    analyzer = CodeAnalyzer(str(p.parent))
    if func_name:
        trace = analyzer.trace_function(p, func_name)
        console.print(trace)
        return
    result = analyzer.explain_file(p)
    console.print(result.summary)
    if not result.annotated_lines:
        return
    table = Table(title=f"Annotations: {p.name}", show_lines=True)
    table.add_column("Line", style="dim", width=4)
    table.add_column("Code", style="white", width=60)
    table.add_column("Explanation / Origin", style="yellow", width=50)
    for al in result.annotated_lines:
        if not show_all and not al.explanation and not al.origin_info:
            continue
        label = ""
        if al.is_definition:
            label = "[bold]▸[/bold] "
        elif al.is_import:
            label = "[blue]→[/blue] "
        elif al.is_call:
            label = "[green]↪[/green] "
        detail = al.explanation
        if al.origin_info:
            detail = (detail + "; " if detail else "") + al.origin_info
        code_display = al.code.rstrip()[:58]
        table.add_row(str(al.number), f"{label}{code_display}", detail[:48] if detail else "")
    console.print(table)


@cli.group()
def routine():
    """Manage automated routines (briefing, email, file organization)"""


@routine.command("list")
@click.option("--user", default=None, help="Filter by user ID")
def routine_list(user: str | None):
    """List configured routines"""
    from raven.core.routine.store import RoutineStore

    store = RoutineStore(settings.resolved_db_path)
    routines = store.list_routines(user_id=user)
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


@routine.command("add")
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
    store.save_routine(routine)
    console.print(f"[green]Routine '{name}' ({routine.id[:8]}) added[/green]")
    console.print(f"  Action: {action}")
    console.print(f"  Schedule: {schedule}")
    console.print(f"  Trigger: {trigger.value}")


@routine.command("remove")
@click.argument("routine_id")
def routine_remove(routine_id: str):
    """Remove a routine"""
    from raven.core.routine.store import RoutineStore

    store = RoutineStore(settings.resolved_db_path)
    r = store.load_routine(routine_id)
    if not r:
        console.print(f"[red]Routine not found: {routine_id}[/red]")
        return
    store.delete_routine(routine_id)
    console.print(f"[yellow]Routine '{r.name}' removed[/yellow]")


@routine.command("pause")
@click.argument("routine_id")
def routine_pause(routine_id: str):
    """Pause a routine"""
    from raven.core.routine.models import RoutineStatus
    from raven.core.routine.store import RoutineStore

    store = RoutineStore(settings.resolved_db_path)
    r = store.load_routine(routine_id)
    if not r:
        console.print(f"[red]Routine not found: {routine_id}[/red]")
        return
    store.update_status(routine_id, RoutineStatus.PAUSED)
    console.print(f"[yellow]Routine '{r.name}' paused[/yellow]")


@routine.command("resume")
@click.argument("routine_id")
def routine_resume(routine_id: str):
    """Resume a paused routine"""
    from raven.core.routine.models import RoutineStatus
    from raven.core.routine.store import RoutineStore

    store = RoutineStore(settings.resolved_db_path)
    r = store.load_routine(routine_id)
    if not r:
        console.print(f"[red]Routine not found: {routine_id}[/red]")
        return
    store.update_status(routine_id, RoutineStatus.ACTIVE)
    console.print(f"[green]Routine '{r.name}' resumed[/green]")


@routine.command("logs")
@click.argument("routine_id")
def routine_logs(routine_id: str):
    """Show execution logs for a routine"""
    from raven.core.routine.store import RoutineStore

    store = RoutineStore(settings.resolved_db_path)
    logs = store.get_logs(routine_id)
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


@cli.group()
def nodes():
    """Manage Raven AI nodes (iOS/Android devices)"""


@nodes.command("list")
def nodes_list():
    """List paired device nodes"""
    console.print("[yellow]Node system: connect iOS/Android devices via Gateway WebSocket[/yellow]")
    console.print("  iOS: https://docs.raven.ai/platforms/ios")
    console.print("  Android: https://docs.raven.ai/platforms/android")
    console.print("\nNo devices currently paired.")


@nodes.command("pair")
@click.argument("device_id")
def nodes_pair(device_id: str):
    """Pair a new device node"""
    console.print(f"[green]Device {device_id} pairing initiated (stub)[/green]")


@cli.group()
def devices():
    """Alias for nodes commands"""


@devices.command("list")
def devices_list():
    """List paired devices"""
    console.print("[yellow]See 'raven nodes list' for device information[/yellow]")


@cli.command()
def tui():
    """Launch the Textual TUI dashboard"""
    import sys

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
        console.print(Panel.fit(
            "[bold]Raven Code Agent[/bold]\n\n"
            "Usage:\n"
            "  raven repl                       # interactive REPL\n"
            "  raven repl \"fix this bug\"        # one-shot + REPL\n"
            "  raven repl -p /path/to/project   # specify project root\n"
            "  raven repl --parallel \"task\"     # parallel session\n"
            "  raven repl --safe                # safe mode (confirm)\n"
            "  raven repl --plan                # read-only plan mode",
            border_style="cyan",
        ))
        return
    _code(task, project, agent, max_steps, safe, plan, model, parallel)


@cli.group()
def flow():
    """RavenFlow — AI workflow orchestrator & gateway"""


@flow.command()
@click.option("--port", default=18789, type=int, help="RavenFlow gateway port")
def serve(port: int):
    """Start the RavenFlow gateway daemon"""
    import asyncio

    from raven.gateway.daemon import RavenFlowDaemon

    console.print(f"[bold]RavenFlow Gateway[/bold] starting on port {port}")
    daemon = RavenFlowDaemon(port=port)
    asyncio.run(daemon.start())


@flow.command(name="ask")
@click.argument("message")
@click.option("--channel", default="cli", help="Source channel")
@click.option("--mode", default="build", help="Agent mode: build, plan, general")
@click.option("--session", default="", help="Session ID")
def flow_ask(message: str, channel: str, mode: str, session: str):
    """Send a message to RavenFlow agent"""
    import asyncio

    import httpx

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


@flow.command(name="sessions")
def flow_sessions():
    """List RavenFlow sessions"""
    import asyncio

    import httpx

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


@cli.command()
@click.option("--wake/--no-wake", default=True, help="Enable/disable wake word detection")
@click.option("--stt", default="whisper", help="STT provider: whisper, google")
@click.option("--tts", default="edge", help="TTS provider: edge, gtts, system")
@click.option("--model", default=None, help="LLM model override")
@click.option("--ghost", is_flag=True, default=False, help="Offline mode — local Whisper + system TTS only")
def voice(wake: bool, stt: str, tts: str, model: str | None, ghost: bool):
    """Start a real-time voice conversation with Raven"""
    if ghost:
        from raven.core.config import apply_ghost_mode
        apply_ghost_mode()
        stt = "whisper"
        tts = "system"
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        console.print("[red]sounddevice not installed. Install: pip install sounddevice[/red]")
        raise SystemExit(1) from None
    from raven.voice.stt import STTConfig, STTProvider
    from raven.voice.tts import TTSConfig, TTSProvider
    stt_providers = {"whisper": STTProvider.WHISPER, "google": STTProvider.GOOGLE}
    tts_providers = {"edge": TTSProvider.EDGETTS, "gtts": TTSProvider.GTTS, "system": TTSProvider.SYSTEM}
    stt_config = STTConfig(provider=stt_providers.get(stt, STTProvider.WHISPER))
    tts_config = TTSConfig(provider=tts_providers.get(tts, TTSProvider.EDGETTS))
    from raven.core.llm import LLMRouter
    llm = LLMRouter()
    async def ask(text: str) -> str:
        resp = await llm.complete([{"role": "user", "content": text}], model=model)
        return resp.content
    from raven.voice.conversation import VoiceConversation
    conv = VoiceConversation(llm_ask=ask, stt_config=stt_config, tts_config=tts_config)
    try:
        asyncio.run(conv.start(wake_mode=wake))
    except KeyboardInterrupt:
        console.print("\n[yellow]Voice conversation ended[/yellow]")


@cli.command()
def upgrade():
    """Update Raven AI to the latest version"""
    import subprocess
    console.print("[bold]Raven Upgrade[/bold]\n")
    repo = Path(__file__).resolve().parent.parent.parent
    os.chdir(str(repo))
    if (repo / ".git").is_dir():
        console.print("[*] Pulling latest code...")
        r = subprocess.run(["git", "pull", "--rebase"], capture_output=True, text=True, timeout=60)  # noqa: S603, S607
        if r.returncode != 0:
            console.print(f"[red]Git pull failed: {r.stderr.strip()}[/red]")
            raise SystemExit(1)
        console.print("[green]  OK[/green]")
    console.print("[*] Updating Python dependencies...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        console.print(f"[yellow]pip install warning: {r.stderr.strip()}[/yellow]")
    else:
        console.print("[green]  OK[/green]")
    web_dir = repo / "web"
    if web_dir.is_dir() and (web_dir / "package.json").is_file():
        console.print("[*] Updating web frontend...")
        r = subprocess.run(["npm", "install"], capture_output=True, text=True, cwd=str(web_dir), timeout=120)  # noqa: S603, S607
        if r.returncode == 0:
            console.print("[green]  OK[/green]")
    console.print("\n[green]Upgrade complete! Run 'raven start' to apply.[/green]")


@cli.command()
@click.option("--lines", "-n", default=50, type=int, help="Number of lines to show")
@click.option("--level", "-l", default="DEBUG", help="Minimum log level (DEBUG, INFO, WARNING, ERROR)")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
def logs(lines: int, level: str, follow: bool):
    """View Raven AI logs"""
    env_path = os.environ.get("RAVEN_LOG_FILE")
    log_path: Path | None
    if env_path:
        log_path = Path(env_path)
    else:
        candidates = [
            Path("data/logs/raven.log"),
            Path("raven.log"),
            Path.home() / ".raven" / "logs" / "raven.log",
        ]
        log_path = next((p for p in candidates if p.exists()), None)
    if log_path is None or not log_path.exists():
        console.print("[red]No log file found. Set RAVEN_LOG_FILE env var or run 'raven start' first.[/red]")
        raise SystemExit(1)
    levels = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level = levels.get(level.upper(), 0)
    try:
        with log_path.open(encoding="utf-8") as f:
            all_lines = f.readlines()
        filtered = []
        for line in all_lines[-lines * 10:]:
            for lvl, lvl_id in levels.items():
                if lvl_id >= min_level and f"| {lvl} |" in line:
                    filtered.append((lvl, line.rstrip()))
                    break
        shown = filtered[-lines:] if len(filtered) > lines else filtered
        for lvl, line in shown:
            style = {"DEBUG": "dim", "INFO": "", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}
            console.print(f"[{style.get(lvl, '')}]{line}[/{style.get(lvl, '')}]")
        if follow:
            console.print("[dim]--- watching for new logs (Ctrl+C to stop) ---[/dim]")
            import time
            try:
                with log_path.open(encoding="utf-8") as f:
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            console.print(line.rstrip())
                        else:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                logger.debug("[logs] follow interrupted by user")
            except Exception as exc:
                console.print(f"[red]Log follow error: {exc}[/red]")
    except Exception as exc:
        console.print(f"[red]Error reading logs: {exc}[/red]")


if __name__ == "__main__":
    cli()
