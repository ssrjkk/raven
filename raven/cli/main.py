from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import click
from loguru import logger
from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from raven.channels.discord.channel import DiscordChannel
from raven.channels.feishu.channel import FeishuChannel
from raven.channels.googlechat.channel import GoogleChatChannel
from raven.channels.irc.channel import IRCChannel
from raven.channels.line.channel import LINECChannel
from raven.channels.matrix.channel import MatrixChannel
from raven.channels.signal.channel import SignalChannel
from raven.channels.slack.channel import SlackChannel
from raven.channels.teams.channel import TeamsChannel
from raven.channels.telegram.channel import TelegramChannel
from raven.channels.webchat.channel import WebChatChannel
from raven.channels.whatsapp.channel import WhatsAppChannel
from raven.core.admin_api import create_admin_router
from raven.core.agent.registry import AgentRegistry
from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.config_store import config_store
from raven.core.config_watcher import ConfigWatcher
from raven.core.db import Database
from raven.core.gateway.gateway import Gateway
from raven.core.health import health
from raven.core.http_client import client_manager
from raven.core.llm import LLMRouter
from raven.core.logging import setup_logging
from raven.core.metrics import metrics
from raven.core.middleware import (
    auth_middleware,
    error_handler_middleware,
    rate_limit_middleware,
    request_id_middleware,
)
from raven.core.models import Message
from raven.core.plugin_loader import PluginLoader
from raven.core.secrets import secrets
from raven.core.webhooks import create_webhook_router

console = Console()


def create_gateway() -> Gateway:
    db_path = settings.resolved_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    plugin_loader = PluginLoader()
    gateway = Gateway(db, plugin_loader)
    return gateway


async def _run_gateway(gateway: Gateway, web_port: int):
    audit_logger.start()
    secrets.load()
    config_watcher = ConfigWatcher()
    await config_watcher.start()
    await gateway.db.connect()
    plugins_dir = Path(__file__).parent.parent / "plugins"
    plugin_loader = gateway.plugin_loader
    for pdir in plugins_dir.iterdir():
        if pdir.is_dir() and pdir.name != "__pycache__":
            plugin_loader.load_from_dir(pdir)
    console.print(Panel.fit(f"[bold green]Loaded {len(plugin_loader.tools)} tools from plugins[/bold green]"))

    from raven.plugins.sessions import plugin as sessions_plugin
    sessions_plugin.init(gateway.db)

    settings.validate()
    audit_logger.log(AuditEventType.SYSTEM_STARTUP, "system", "gateway", detail={"plugins": len(plugin_loader.tools)})

    telegram = TelegramChannel()
    discord = DiscordChannel()
    webchat = WebChatChannel(gateway.db)
    slack = SlackChannel()
    whatsapp = WhatsAppChannel()
    matrix = MatrixChannel()
    googlechat = GoogleChatChannel()
    sig_ch = SignalChannel()
    irc = IRCChannel()
    teams = TeamsChannel()
    feishu = FeishuChannel()
    line = LINECChannel()

    telegram.on_message(gateway.handle_message)
    discord.on_message(gateway.handle_message)
    webchat.on_message(gateway.handle_message)
    slack.on_message(gateway.handle_message)
    whatsapp.on_message(gateway.handle_message)
    matrix.on_message(gateway.handle_message)
    googlechat.on_message(gateway.handle_message)
    sig_ch.on_message(gateway.handle_message)
    irc.on_message(gateway.handle_message)
    teams.on_message(gateway.handle_message)
    feishu.on_message(gateway.handle_message)
    line.on_message(gateway.handle_message)

    gateway.register_channel(telegram)
    gateway.register_channel(discord)
    gateway.register_channel(webchat)
    gateway.register_channel(slack)
    gateway.register_channel(whatsapp)
    gateway.register_channel(matrix)
    gateway.register_channel(googlechat)
    gateway.register_channel(sig_ch)
    gateway.register_channel(irc)
    gateway.register_channel(teams)
    gateway.register_channel(feishu)
    gateway.register_channel(line)

    import signal

    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware

    api_app = webchat.app

    api_app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_cors_origins.split(",") if settings.web_cors_origins != "*" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api_app.middleware("http")(request_id_middleware)
    api_app.middleware("http")(rate_limit_middleware)
    api_app.middleware("http")(auth_middleware)
    api_app.middleware("http")(error_handler_middleware)

    api_app.state.slack_channel = slack
    api_app.state.whatsapp_channel = whatsapp
    api_app.state.matrix_channel = matrix
    api_app.state.googlechat_channel = googlechat
    api_app.state.signal_channel = signal
    api_app.state.irc_channel = irc
    api_app.state.teams_channel = teams
    api_app.state.feishu_channel = feishu
    api_app.state.line_channel = line
    stop_event = asyncio.Event()
    api_app.state.stop_event = stop_event

    webhook_router = create_webhook_router(gateway.db, gateway.handle_message)
    api_app.include_router(webhook_router)

    web_dist = Path(__file__).parent.parent.parent / "web" / "dist"
    if web_dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        api_app.mount("/dashboard", StaticFiles(directory=str(web_dist), html=True), name="dashboard")
        logger.info("Web dashboard mounted from {}", web_dist)
    else:
        logger.info("Web dashboard not built (no web/dist). Run cd web && npm install && npm run build")

    def _get_channels():
        return gateway.channels

    def _get_registry():
        return gateway.registry

    def _get_gateway():
        return gateway

    admin_router = create_admin_router(_get_channels, _get_registry, _get_gateway)
    api_app.include_router(admin_router)

    @api_app.get("/api/status")
    async def api_status():
        return {
            "status": "running",
            "channels": list(gateway.channels.keys()),
            "plugins": len(plugin_loader.tools),
            "agents": gateway.registry.list_agents(),
            "model": settings.default_model,
            "version": "1.0.0",
        }

    @api_app.get("/api/agents")
    async def api_agents():
        return gateway.registry.list_agents()

    @api_app.get("/api/monitor/list")
    async def api_monitor_list():
        from raven.core.monitor.store import MonitorStore
        store = MonitorStore(settings.resolved_db_path)
        monitors = store.list_monitors()
        return [
            {
                "id": m.id, "name": m.name, "type": m.type.value,
                "target": m.target, "interval_seconds": m.interval_seconds,
                "status": m.status.value,
                "last_check": {"status": m.last_check.status, "checked_at": m.last_check.checked_at} if m.last_check else None,
            }
            for m in monitors
        ]

    @api_app.post("/api/monitor/{action}/{monitor_id}")
    async def api_monitor_toggle(action: str, monitor_id: str):
        from raven.core.monitor.store import MonitorStore
        from raven.core.monitor.models import MonitorStatus
        store = MonitorStore(settings.resolved_db_path)
        if action == "pause":
            store.update_status(monitor_id, MonitorStatus.PAUSED)
        elif action == "resume":
            store.update_status(monitor_id, MonitorStatus.ACTIVE)
        return {"ok": True}

    @api_app.get("/api/routine/list")
    async def api_routine_list():
        from raven.core.routine.store import RoutineStore
        store = RoutineStore(settings.resolved_db_path)
        routines = store.list_routines()
        return [
            {
                "id": r.id, "name": r.name, "action": r.action.value,
                "schedule": r.schedule, "trigger": r.trigger.value,
                "status": r.status.value, "last_run_status": r.last_run_status,
            }
            for r in routines
        ]

    @api_app.post("/api/routine/{action}/{routine_id}")
    async def api_routine_toggle(action: str, routine_id: str):
        from raven.core.routine.store import RoutineStore
        from raven.core.routine.models import RoutineStatus
        store = RoutineStore(settings.resolved_db_path)
        if action == "pause":
            store.update_status(routine_id, RoutineStatus.PAUSED)
        elif action == "resume":
            store.update_status(routine_id, RoutineStatus.ACTIVE)
        return {"ok": True}

    @api_app.get("/api/task/list")
    async def api_task_list():
        from raven.core.task_engine.store import TaskStore
        store = TaskStore(settings.resolved_db_path)
        tasks = store.list_tasks()
        return [
            {
                "id": t.id, "goal": t.goal, "status": t.status.value,
                "steps": [
                    {"order": s.order, "description": s.description, "tool": s.tool, "status": s.status.value}
                    for s in t.steps
                ],
                "created_at": t.created_at,
            }
            for t in tasks
        ]

    @api_app.post("/api/task/run")
    async def api_task_run(body: dict):
        from raven.core.task_engine.store import TaskStore
        from raven.core.task_engine.planner import TaskPlanner
        from raven.core.task_engine.runner import TaskRunner
        from raven.tools.register_all import create_tool_registry
        goal = body.get("goal", "")
        if not goal:
            from fastapi import HTTPException
            raise HTTPException(400, "goal required")
        tools = create_tool_registry()
        store = TaskStore(settings.resolved_db_path)
        planner = TaskPlanner(tools)
        runner = TaskRunner(store, tools)
        task = await planner.plan(goal, gateway.llm)
        await runner.submit(task)
        asyncio.create_task(runner.wait(task.id, timeout=600))
        return {"id": task.id}

    @api_app.post("/api/task/{task_id}/cancel")
    async def api_task_cancel(task_id: str):
        from raven.core.task_engine.store import TaskStore
        from raven.core.task_engine.runner import TaskRunner
        from raven.tools.register_all import create_tool_registry
        tools = create_tool_registry()
        store = TaskStore(settings.resolved_db_path)
        runner = TaskRunner(store, tools)
        ok = await runner.cancel(task_id)
        return {"ok": ok}

    @api_app.get("/api/code/list")
    async def api_code_sessions():
        from raven.core.coder.session import CodingSessionManager
        mgr = CodingSessionManager(settings.resolved_db_path)
        sessions = mgr.list_sessions()
        return [
            {
                "id": s.id, "goal": s.goal, "status": s.status.value,
                "project_path": s.project_path, "files": len(s.files) if hasattr(s, "files") else 0,
            }
            for s in sessions
        ]

    @api_app.get("/api/health")
    async def api_health():
        return await health.check_all()

    @api_app.get("/api/health/ready")
    async def api_ready():
        return await health.check_readiness()

    @api_app.get("/api/health/live")
    async def api_live():
        return {"status": "ok"}

    @api_app.get("/api/metrics")
    async def api_metrics():
        return metrics.snapshot()

    @api_app.get("/api/metrics/prometheus")
    async def api_metrics_prometheus():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(metrics.prometheus())

    @api_app.post("/api/shutdown")
    async def api_shutdown():
        logger.info("Shutdown requested via API")
        audit_logger.sensitive("shutdown", "api", "system", True)
        stop_event.set()
        return {"ok": True}

    class AgentAssign(BaseModel):
        agent_id: str = "default"

    class RavenRequest(BaseModel):
        action: str
        code: str = ""
        context: str = ""

    @api_app.post("/api/raven")
    async def api_raven(body: RavenRequest):
        logger.info("Raven API call: action={}", body.action)
        audit_logger.log(AuditEventType.COMMAND, "api", "raven", detail={"action": body.action})
        try:
            session = await gateway.db.get_or_create_session(
                f"vscode:{body.action}:default", "vscode", "vscode_user"
            )
            agent_obj = gateway.registry.create_agent(session)
            full = ""
            async for token in agent_obj.run(f"{body.action}:\n{body.code[:2000]}\n\nContext: {body.context[:500]}"):
                full += token
            return {"response": full[:5000]}
        except Exception as e:
            logger.error("Raven API error: {}", e)
            return {"response": f"Error: {e}"}

    @api_app.post("/api/sessions/{session_id}/agent")
    async def api_set_agent(session_id: str, body: AgentAssign):
        logger.info("Session {} → agent {}", session_id, body.agent_id)
        return {"ok": True, "session_id": session_id, "agent_id": body.agent_id}

    stop_event = asyncio.Event()

    def shutdown_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            pass

    async def run_all():
        await gateway.start()
        config = uvicorn.Config(api_app, host="0.0.0.0", port=web_port, log_level="info", ws="auto")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        await stop_event.wait()
        logger.info("Shutting down...")
        shutdown_task = asyncio.create_task(_shutdown(gateway, server_task))
        try:
            await asyncio.wait_for(shutdown_task, timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Shutdown timed out, forcing exit")
            os._exit(1)

    async def _shutdown(gw: Gateway, sv_task: asyncio.Task):
        try:
            await asyncio.wait_for(gw.llm.cleanup(), timeout=5)
        except Exception:
            pass
        try:
            await asyncio.wait_for(gw.stop(), timeout=10)
        except Exception:
            pass
        try:
            await asyncio.wait_for(gw.db.disconnect(), timeout=5)
        except Exception:
            pass
        try:
            await asyncio.wait_for(client_manager.close(), timeout=5)
        except Exception:
            pass
        try:
            await config_watcher.stop()
        except Exception:
            pass
        try:
            audit_logger.stop()
        except Exception:
            pass
        sv_task.cancel()
        try:
            await sv_task
        except asyncio.CancelledError:
            pass
        logger.info("Shutdown complete")

    try:
        await run_all()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupted, shutting down...")
        try:
            await asyncio.wait_for(gateway.stop(), timeout=10)
        except Exception:
            pass
        try:
            await asyncio.wait_for(gateway.db.disconnect(), timeout=5)
        except Exception:
            pass


@click.group()
def cli():
    """Raven AI — Personal AI Assistant 24/7"""


@cli.command()
@click.option("--daemon", is_flag=True, help="Run as daemon process")
@click.option("--port", default=None, type=int, help="Web UI port")
@click.option("--stateless", is_flag=True, default=False, help="Run without memory/context persistence")
def start(daemon: bool, port: Optional[int], stateless: bool):
    """Start the Raven AI gateway"""
    setup_logging()
    if daemon:
        console.print("[yellow]Daemon mode requested — use systemd or launchd instead[/yellow]")
        console.print("  systemd: deploy/raven.service")
        console.print("  launchd: sudo cp deploy/com.raven.plist /Library/LaunchDaemons/")
        return

    web_port = port or settings.web_port
    gateway = create_gateway()
    if stateless:
        for agent_conf in gateway.registry._configs.values():
            agent_conf.stateless = True
    console.print(Panel.fit(
        "[bold blue]🐦 Raven AI[/bold blue]\n"
        f"[dim]Web UI: http://localhost:{web_port}[/dim]\n"
        f"[dim]Model: {settings.default_model}[/dim]"
        + ("\n[dim]Mode: stateless[/dim]" if stateless else "")
    ))
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
        db = Database(settings.resolved_db_path)
        await db.connect()
        sessions = await db.get_sessions()
        await db.disconnect()

        import httpx
        api_ok = False
        try:
            r = httpx.get(f"http://localhost:{settings.web_port}/api/status", timeout=3)
            api_ok = r.is_success
        except Exception:
            pass

        table = Table(title="Raven AI Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")
        table.add_row("API", "🟢 Running" if api_ok else "🔴 Stopped", f"port {settings.web_port}")
        table.add_row("Sessions", "🟢", str(len(sessions)))
        table.add_row("Model", "⚪", settings.default_model)
        table.add_row("DM Policy", "⚪", settings.dm_policy)
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

    checks.append(("Config Store", f"✅ {config_store.path}" if config_store.path.exists() else "⚠️  Not initialized"))
    checks.append(("Python", sys.version))
    checks.append(("DB Path", str(settings.resolved_db_path)))

    has_any_key = bool(cfg.get("openrouter_api_key") or cfg.get("anthropic_api_key") or cfg.get("openai_api_key") or cfg.get("ollama_base_url"))
    checks.append(("LLM Provider", "✅ Configured" if has_any_key else "⚠️  No provider configured"))

    provider_names = []
    if cfg.get("openrouter_api_key"): provider_names.append("OpenRouter")
    if cfg.get("anthropic_api_key"): provider_names.append("Anthropic")
    if cfg.get("openai_api_key"): provider_names.append("OpenAI")
    if cfg.get("ollama_base_url"): provider_names.append("Ollama")
    if provider_names:
        checks.append(("Providers", ", ".join(provider_names)))

    checks.append(("Default Model", cfg.get("default_model", "—")))
    checks.append(("Telegram", "✅ Configured" if cfg.get("telegram_bot_token") else "⚠️  Not set"))
    checks.append(("Discord", "✅ Configured" if cfg.get("discord_bot_token") else "⚠️  Not set"))
    checks.append(("Slack", "✅ Configured" if cfg.get("slack_bot_token") else "⚠️  Not set"))
    checks.append(("DM Policy", cfg.get("dm_policy", "pairing")))
    checks.append(("Web Port", str(cfg.get("web_port", 18888))))
    checks.append(("Web Secret Key", "✅ Set" if cfg.get("web_secret_key") else "⚠️  Not set"))

    has_crypto = __import__("importlib.util").util.find_spec("cryptography")
    checks.append(("Secrets Encryption", "✅ Available" if has_crypto else "⚠️  Install cryptography for secrets"))

    try:
        import pywin32  # noqa: F401
        checks.append(("Windows Service", "✅ pywin32 available"))
    except ImportError:
        if sys.platform == "win32":
            checks.append(("Windows Service", "⚠️  Install pywin32 for service support"))
    except Exception:
        pass

    try:
        import playwright  # noqa: F401
        checks.append(("Playwright", "✅ Installed"))
    except ImportError:
        checks.append(("Playwright", "⚠️  Not installed (browser plugin limited)"))

    api_ok = False
    try:
        import httpx
        r = httpx.get(f"http://localhost:{settings.web_port}/api/status", timeout=3)
        api_ok = r.is_success
    except Exception:
        pass
    checks.append(("API", "🟢 Running" if api_ok else "🔴 Stopped"))

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
            capture_output=True, text=True, timeout=30,
        )
        if "Would install" in result.stdout or "Requirement already satisfied" not in result.stdout:
            console.print("[yellow]Update available[/yellow]" if not dry_run else "[green]Run without --dry-run to update[/green]")
            if not dry_run:
                console.print("[bold]Updating...[/bold]")
                upg = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", "raven-agent"],
                    capture_output=True, text=True, timeout=120,
                )
                if upg.returncode == 0:
                    console.print("[green]✅ Update complete![/green]")
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
        db = Database(settings.resolved_db_path)
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
        db = Database(settings.resolved_db_path)
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
@click.option("--channel", required=True, help="Target channel (telegram, discord, webchat, slack, whatsapp, matrix, googlechat, signal, irc, teams, feishu, line)")
@click.option("--user", required=True, help="User ID")
@click.option("--text", required=True, help="Message text")
@click.option("--session", default=None, help="Session ID (optional)")
def msg_send(channel: str, user: str, text: str, session: Optional[str]):
    """Send a message to a user via Raven AI"""
    async def _send():
        db = Database(settings.resolved_db_path)
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
    table.add_row("OpenRouter", "✅" if settings.openrouter_api_key else "❌", "✓" if settings.default_model.startswith("openrouter/") else "")
    table.add_row("Anthropic", "✅" if settings.anthropic_api_key else "❌", "✓" if settings.default_model.startswith("claude") else "")
    table.add_row("OpenAI", "✅" if settings.openai_api_key else "❌", "")
    table.add_row("Ollama", "✅" if settings.ollama_base_url else "❌", "✓" if settings.default_model.startswith("ollama/") else "")
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
        db = Database(settings.resolved_db_path)
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
def db_migrate(target: Optional[int]):
    """Run pending database migrations"""
    async def _migrate():
        db = Database(settings.resolved_db_path)
        await db.connect()
        await db.disconnect()
        console.print("[green]Migrations complete[/green]")
    asyncio.run(_migrate())


@db.command("backup")
@click.argument("output", default=None, required=False)
def db_backup(output: Optional[str]):
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
        db = Database(settings.resolved_db_path)
        await db.connect()
        version = await db.migrator.get_current_version()
        await db.disconnect()
        console.print(f"Database schema version: [bold]{version}[/bold]")
    asyncio.run(_version())


@cli.command()
@click.option("--message", required=True, help="Message to send to agent")
@click.option("--agent", "agent_id", default="default", help="Agent ID to use")
@click.option("--channel", default="cli", help="Channel to simulate")
@click.option("--thinking", default=None, help="Thinking level: low, medium, high")
def agent(message: str, agent_id: str, channel: str, thinking: Optional[str]):
    """Send a message to the Raven AI agent and get a response"""
    async def _agent():
        db = Database(settings.resolved_db_path)
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
def task_list(user: Optional[str], status: Optional[str], limit: int):
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
            "pending": "⏳", "running": "🔄", "completed": "✅",
            "failed": "❌", "cancelled": "🚫", "paused": "⏸",
        }
        icon = status_icon.get(t.status.value, "❓")
        done = sum(1 for s in t.steps if s.status.value == "completed")
        total = len(t.steps)
        created = __import__("time").strftime("%H:%M", __import__("time").localtime(t.created_at))
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
    console.print(Panel.fit(f"[bold]Task: {t.id}[/bold]\n"
                            f"[cyan]Goal:[/cyan] {t.goal}\n"
                            f"[cyan]Status:[/cyan] {t.status.value}\n"
                            f"[cyan]Steps:[/cyan] {len(t.steps)}\n"
                            f"[cyan]Created:[/cyan] {__import__('time').ctime(t.created_at)}"))
    for i, step in enumerate(t.steps):
        icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌", "cancelled": "🚫"}.get(step.status.value, "❓")
        console.print(f"  {icon} Step {i+1}: {step.description} [dim]({step.tool})[/dim]")
        if step.error:
            console.print(f"     [red]Error: {step.error}[/red]")


@task.command("run")
@click.argument("goal")
@click.option("--user", default="cli", help="User ID")
@click.option("--channel", default="cli", help="Channel")
def task_run(goal: str, user: str, channel: str):
    """Plan and execute a goal as a task"""
    from raven.core.task_engine.store import TaskStore
    from raven.core.task_engine.runner import TaskRunner
    from raven.core.task_engine.planner import TaskPlanner
    from raven.tools.register_all import create_tool_registry
    from raven.core.llm import LLMRouter

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
            console.print(f"  {i+1}. {step.description} [dim]({step.tool})[/dim]")

        await runner.submit(task)
        console.print(f"[green]Task {task.id[:8]} submitted, running...[/green]")

        task = await runner.wait(task.id, timeout=300)
        if task.status.value == "completed":
            console.print("[green]✅ Task completed![/green]")
        elif task.status.value == "failed":
            console.print(f"[red]❌ Task failed: {task.error}[/red]")
        elif task.status.value == "cancelled":
            console.print("[yellow]🚫 Task cancelled[/yellow]")
        else:
            console.print(f"[yellow]Task status: {task.status.value}[/yellow]")

    asyncio.run(_run())


@task.command("cancel")
@click.argument("task_id")
def task_cancel(task_id: str):
    """Cancel a running task"""
    from raven.core.task_engine.store import TaskStore
    from raven.core.task_engine.runner import TaskRunner
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
    from raven.core.task_engine.store import TaskStore
    from raven.core.task_engine.runner import TaskRunner
    from raven.tools.register_all import create_tool_registry

    async def _retry():
        tools = create_tool_registry()
        store = TaskStore(settings.resolved_db_path)
        runner = TaskRunner(store, tools)
        task = store.load_task(task_id)
        if not task:
            console.print(f"[red]Task not found: {task_id}[/red]")
            return
        task.status = __import__("raven.core.task_engine.models", fromlist=["TaskStatus"]).TaskStatus.PENDING  # noqa
        task.error = None
        task.current_step_index = 0
        for step in task.steps:
            step.status = __import__("raven.core.task_engine.models", fromlist=["TaskStatus"]).TaskStatus.PENDING
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
def monitor_list(user: Optional[str], status: Optional[str]):
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
        icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(m.status.value, "❓")
        last = ""
        if m.last_check:
            last = f"{'✅' if m.last_check.status == 'up' else '❌'} {m.last_check.checked_at:.0f}s ago"
        table.add_row(m.id[:8], m.name, m.type.value, m.target[:40],
                      f"{m.interval_seconds}s", f"{icon} {m.status.value}", last)
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
    from raven.core.monitor.models import Condition, ConditionOperator, Monitor, MonitorType, MonitorStatus
    from raven.core.monitor.store import MonitorStore

    parsed_conditions = []
    for c in conditions:
        parts = c.split("!", 1) if "!" in c else c.split("=", 1) if "=" in c else c.split(">", 1) if ">" in c else c.split("<", 1) if "<" in c else [c, ""]
        if len(parts) == 2:
            op_str = "!=" if "!" in c else "=" if "=" in c else ">" if ">" in c else "<"
            op_map = {"=": ConditionOperator.EQ, "!=": ConditionOperator.NE, ">": ConditionOperator.GT, "<": ConditionOperator.LT}
            val = parts[1]
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
            parsed_conditions.append(Condition(metric=parts[0].strip(), operator=op_map.get(op_str, ConditionOperator.EQ), value=val))

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
        for c in parsed_conditions:
            console.print(f"  ⚡ Condition: {c.metric} {c.operator.value} {c.value}")


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
        t = __import__("time").strftime("%H:%M:%S", __import__("time").localtime(c.checked_at))
        icon = "✅" if c.status == "up" else "❌"
        ms = f"{c.response_time_ms:.0f}ms" if c.response_time_ms else ""
        trig = "🔔" if c.triggered else ""
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
    from raven.core.coder.indexer import CodeIndexer
    from pathlib import Path
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        console.print(f"[red]Not a directory: {p}[/red]")
        return
    with console.status("[bold]Indexing...", spinner="dots"):
        indexer = CodeIndexer(str(p))
        files = indexer.index(max_files=max_files)
    summary = indexer.summary()
    console.print(f"[green]Indexed {summary['files']} files[/green]")
    for lang, count in summary.get("languages", {}).items():
        console.print(f"  {lang}: {count} files")


@code.command("search")
@click.argument("query")
@click.argument("path", default=".", required=False)
def code_search(query: str, path: str):
    """Search indexed codebase for symbols"""
    from raven.core.coder.indexer import CodeIndexer
    from pathlib import Path

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
    from raven.core.coder.review import CodeReviewer
    from pathlib import Path

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
        table.add_row(str(c.line), f"[{severity_colors.get(c.severity.value, 'white')}]{c.severity.value}[/]", c.message, c.suggestion)
    console.print(table)


@code.command("start")
@click.argument("goal")
@click.option("--project", default=".", help="Project path")
@click.option("--user", default="cli", help="User ID")
def code_start(goal: str, project: str, user: str):
    """Start a coding session"""
    from raven.core.coder.models import CodingSession
    from raven.core.coder.session import CodingSessionManager
    from pathlib import Path

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
    console.print(Panel.fit(f"[bold]Coding Session: {session.id}[/bold]\n"
                            f"[cyan]Goal:[/cyan] {session.goal}\n"
                            f"[cyan]Project:[/cyan] {session.project_path}\n"
                            f"[cyan]Status:[/cyan] {session.status.value}\n"
                            f"[cyan]Files:[/cyan] {len(session.files)}\n"
                            f"[cyan]Messages:[/cyan] {len(session.history)}"))


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


@cli.group()
def routine():
    """Manage automated routines (briefing, email, file organization)"""


@routine.command("list")
@click.option("--user", default=None, help="Filter by user ID")
def routine_list(user: Optional[str]):
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
        icon = {"active": "🟢", "paused": "⏸", "error": "🔴"}.get(r.status.value, "❓")
        last = r.last_run_status if r.last_run_status else "—"
        table.add_row(r.id[:8], r.name, r.action.value, r.schedule, f"{icon} {r.status.value}", last)
    console.print(table)


@routine.command("add")
@click.option("--name", required=True, help="Routine name")
@click.option("--action", required=True, type=click.Choice(["send_briefing", "send_message", "check_email", "organize_files"]))
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
        name=name, description=description,
        action=RoutineAction(action), trigger=trigger,
        schedule=schedule, status=RoutineStatus.ACTIVE,
        user_id=user, channel=channel,
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
        t = __import__("time").strftime("%H:%M:%S", __import__("time").localtime(log.created_at))
        icon = "✅" if log.status == "success" else "❌"
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


if __name__ == "__main__":
    cli()
