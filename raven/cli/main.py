from __future__ import annotations
import os
import sys
import json
import signal
import asyncio
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from loguru import logger

from raven.core.config import settings
from raven.core.db import Database
from raven.core.llm import LLMRouter
from raven.core.models import Message
from raven.core.agent.registry import AgentRegistry
from raven.core.gateway.gateway import Gateway
from raven.core.plugin_loader import PluginLoader
from raven.core.logging import setup_logging, audit
from raven.core.health import health
from raven.core.metrics import metrics
from raven.core.middleware import request_id_middleware, rate_limit_middleware, auth_middleware, rate_limiter
from pydantic import BaseModel
from raven.channels.telegram.channel import TelegramChannel
from raven.channels.discord.channel import DiscordChannel
from raven.channels.webchat.channel import WebChatChannel
from raven.channels.slack.channel import SlackChannel
from raven.channels.whatsapp.channel import WhatsAppChannel
from raven.channels.matrix.channel import MatrixChannel
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
    await gateway.db.connect()
    plugins_dir = Path(__file__).parent.parent / "plugins"
    plugin_loader = gateway.plugin_loader
    for pdir in plugins_dir.iterdir():
        if pdir.is_dir() and pdir.name != "__pycache__":
            plugin_loader.load_from_dir(pdir)
    console.print(Panel.fit(f"[bold green]Loaded {len(plugin_loader.tools)} tools from plugins[/bold green]"))

    settings.validate()
    audit.log("system", "startup", "gateway", f"plugins={len(plugin_loader.tools)}")

    telegram = TelegramChannel()
    discord = DiscordChannel()
    webchat = WebChatChannel(gateway.db)
    slack = SlackChannel()
    whatsapp = WhatsAppChannel()
    matrix = MatrixChannel()

    telegram.on_message(gateway.handle_message)
    discord.on_message(gateway.handle_message)
    webchat.on_message(gateway.handle_message)
    slack.on_message(gateway.handle_message)
    whatsapp.on_message(gateway.handle_message)
    matrix.on_message(gateway.handle_message)

    gateway.register_channel(telegram)
    gateway.register_channel(discord)
    gateway.register_channel(webchat)
    gateway.register_channel(slack)
    gateway.register_channel(whatsapp)
    gateway.register_channel(matrix)

    import uvicorn
    from fastapi import FastAPI
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

    api_app.state.slack_channel = slack
    api_app.state.whatsapp_channel = whatsapp
    api_app.state.matrix_channel = matrix

    webhook_router = create_webhook_router(gateway.db, gateway.handle_message)
    api_app.include_router(webhook_router)

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
        audit.sensitive_op("api", "shutdown", "system", True)
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
        audit.log("api", "raven", "inference", body.action)
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
    """Diagnose configuration and dependencies"""
    console.print(Panel.fit("[bold]Raven AI Doctor[/bold]"))
    checks = []

    checks.append(("Config file", "✅ Found" if Path(".env").exists() else "⚠️  Missing .env (using defaults)"))
    checks.append(("Python", sys.version))
    checks.append(("DB Path", str(settings.resolved_db_path)))
    checks.append(("OpenRouter", "✅ Configured" if settings.openrouter_api_key else "⚠️  Not set"))
    checks.append(("Anthropic", "✅ Configured" if settings.anthropic_api_key else "⚠️  Not set"))
    checks.append(("Telegram", "✅ Configured" if settings.telegram_bot_token else "⚠️  Not set"))
    checks.append(("Discord", "✅ Configured" if settings.discord_bot_token else "⚠️  Not set"))
    checks.append(("Slack", "✅ Configured" if settings.slack_bot_token else "⚠️  Not set"))
    checks.append(("WhatsApp", "✅ Configured" if settings.web_secret_key else "⚠️  Needs web_secret_key"))
    checks.append(("Matrix", "✅ Configured" if settings.matrix_homeserver else "⚠️  Not set"))
    checks.append(("DM Policy", settings.dm_policy))
    checks.append(("Web Secret Key", "✅ Set" if settings.web_secret_key else "⚠️  Not set"))
    checks.append(("JSON Logging", "✅ On" if settings.json_log else "❌ Off"))
    checks.append(("Rate Limit", f"{settings.rate_limit_max}/min"))
    checks.append(("LLM Retry", f"{settings.llm_retry_max} attempts"))

    try:
        import playwright
        checks.append(("Playwright", "✅ Installed"))
    except ImportError:
        checks.append(("Playwright", "⚠️  Not installed (browser plugin limited)"))

    table = Table(show_header=False)
    table.add_column("Check", style="cyan")
    table.add_column("Result")
    for name, result in checks:
        table.add_row(name, result)
    console.print(table)


@cli.command()
def onboard():
    """Interactive setup wizard"""
    console.print(Panel.fit("[bold]🐦 Welcome to Raven AI Setup Wizard[/bold]"))

    setup = {}
    setup["openrouter"] = click.prompt("OpenRouter API Key (optional)", default="")
    setup["anthropic"] = click.prompt("Anthropic API Key (optional)", default="")
    setup["telegram"] = click.prompt("Telegram Bot Token (optional)", default="")
    setup["discord"] = click.prompt("Discord Bot Token (optional)", default="")
    setup["slack"] = click.prompt("Slack Bot Token (optional)", default="")
    setup["policy"] = click.prompt("DM Policy [pairing/open/closed]", default="pairing")
    setup["port"] = click.prompt("Web UI Port", default=18888, type=int)
    setup["secret"] = click.prompt("Web Secret Key (API auth, optional)", default="")

    env_path = Path(".env")
    existing = env_path.read_text() if env_path.exists() else ""
    lines = existing.splitlines() if existing else []
    env_vars = {}
    for line in lines:
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

    if setup["openrouter"]:
        env_vars["OPENROUTER_API_KEY"] = setup["openrouter"]
    if setup["anthropic"]:
        env_vars["ANTHROPIC_API_KEY"] = setup["anthropic"]
    if setup["telegram"]:
        env_vars["TELEGRAM_BOT_TOKEN"] = setup["telegram"]
    if setup["discord"]:
        env_vars["DISCORD_BOT_TOKEN"] = setup["discord"]
    if setup["slack"]:
        env_vars["SLACK_BOT_TOKEN"] = setup["slack"]
    env_vars["DM_POLICY"] = setup["policy"]
    env_vars["WEB_PORT"] = str(setup["port"])
    if setup["secret"]:
        env_vars["WEB_SECRET_KEY"] = setup["secret"]

    content = "\n".join(f"{k}={v}" for k, v in env_vars.items())
    env_path.write_text(content)
    console.print("[green]✅ Configuration saved to .env[/green]")
    console.print("\nRun [bold]raven start[/bold] to launch!")


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
@click.option("--channel", required=True, help="Target channel (telegram, discord, webchat, slack, whatsapp)")
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


if __name__ == "__main__":
    cli()
