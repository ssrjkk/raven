from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from pathlib import Path
from typing import Any

import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

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
from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.config_watcher import ConfigWatcher
from raven.core.db import DatabaseFactory
from raven.core.gateway.aios_adapter import get_aios_adapter
from raven.core.gateway.gateway import Gateway
from raven.core.health import health
from raven.core.http_client import client_manager
from raven.core.metrics import metrics
from raven.core.middleware import (
    auth_middleware,
    error_handler_middleware,
    input_sanitize_middleware,
    rate_limit_middleware,
    request_id_middleware,
)
from raven.core.monitor.engine import MonitorEngine
from raven.core.monitor.store import MonitorStore
from raven.core.plugin_loader import PluginLoader
from raven.core.routine.engine import RoutineEngine
from raven.core.routine.store import RoutineStore
from raven.core.webhooks import create_webhook_router
from raven.monitors.register_all import register_all_monitors
from raven.routines.register_all import register_all_routines


def create_gateway() -> Gateway:
    db = DatabaseFactory.create()
    if hasattr(db, "dsn"):
        logger.info("Using PostgreSQL database")
    else:
        db.db_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_loader = PluginLoader()
    gateway = Gateway(db, plugin_loader)
    return gateway


async def _run_gateway(gateway: Gateway, web_port: int):
    audit_logger.start()
    config_watcher = ConfigWatcher()
    await config_watcher.start()
    await gateway.db.connect()
    from raven.core.secrets import secrets as _secrets

    await _secrets.bind_db(gateway.db)
    plugins_dir = Path(__file__).parent.parent / "plugins"
    plugin_loader = gateway.plugin_loader
    for pdir in plugins_dir.iterdir():
        if pdir.is_dir() and pdir.name != "__pycache__":
            plugin_loader.load_from_dir(pdir)
    logger.info("Loaded {} tools from plugins", len(plugin_loader.tools))

    from raven.plugins.sessions import plugin as sessions_plugin

    sessions_plugin.init(gateway.db)

    settings.validate_settings()
    await audit_logger.log(AuditEventType.SYSTEM_STARTUP, "system", "gateway", detail={"plugins": len(plugin_loader.tools)})

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

    await telegram.on_message(gateway.handle_message)
    await discord.on_message(gateway.handle_message)
    await webchat.on_message(gateway.handle_message)
    await slack.on_message(gateway.handle_message)
    await whatsapp.on_message(gateway.handle_message)
    await matrix.on_message(gateway.handle_message)
    await googlechat.on_message(gateway.handle_message)
    await sig_ch.on_message(gateway.handle_message)
    await irc.on_message(gateway.handle_message)
    await teams.on_message(gateway.handle_message)
    await feishu.on_message(gateway.handle_message)
    await line.on_message(gateway.handle_message)

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
    api_app.middleware("http")(input_sanitize_middleware)

    api_app.state.slack_channel = slack
    api_app.state.whatsapp_channel = whatsapp
    api_app.state.matrix_channel = matrix
    api_app.state.googlechat_channel = googlechat
    api_app.state.signal_channel = sig_ch
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

    api_app.include_router(get_aios_adapter().get_bridge_router())

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
        eng: MonitorEngine = api_app.state.monitor_engine
        monitors = eng.list_monitors()
        return [
            {
                "id": m.id,
                "name": m.name,
                "type": m.type.value,
                "target": m.target,
                "interval_seconds": m.interval_seconds,
                "status": m.status.value,
                "last_check": {"status": m.last_check.status, "checked_at": m.last_check.checked_at}
                if m.last_check
                else None,
            }
            for m in monitors
        ]

    @api_app.post("/api/monitor/{action}/{monitor_id}")
    async def api_monitor_toggle(action: str, monitor_id: str):
        eng: MonitorEngine = api_app.state.monitor_engine
        if action == "pause":
            eng.pause_monitor(monitor_id)
        elif action == "resume":
            eng.resume_monitor(monitor_id)
        return {"ok": True}

    @api_app.get("/api/routine/list")
    async def api_routine_list():
        eng: RoutineEngine = api_app.state.routine_engine
        return [
            {
                "id": r.id,
                "name": r.name,
                "action": r.action.value,
                "schedule": r.schedule,
                "trigger": r.trigger.value,
                "status": r.status.value,
                "last_run_status": r.last_run_status,
            }
            for r in eng._store.list_routines()
        ]

    @api_app.post("/api/routine/{action}/{routine_id}")
    async def api_routine_toggle(action: str, routine_id: str):
        eng: RoutineEngine = api_app.state.routine_engine
        if action == "pause":
            eng.pause_routine(routine_id)
        elif action == "resume":
            eng.resume_routine(routine_id)
        return {"ok": True}

    @api_app.get("/api/task/list")
    async def api_task_list():
        from raven.core.task_engine.store import TaskStore

        store = TaskStore(settings.resolved_db_path)
        tasks = store.list_tasks()
        return [
            {
                "id": t.id,
                "goal": t.goal,
                "status": t.status.value,
                "steps": [
                    {"order": s.order, "description": s.description, "tool": s.tool, "status": s.status.value}
                    for s in t.steps
                ],
                "created_at": t.created_at,
            }
            for t in tasks
        ]

    @api_app.post("/api/task/run")
    async def api_task_run(body: dict[str, Any]):
        from raven.core.task_engine.planner import TaskPlanner
        from raven.core.task_engine.runner import TaskRunner
        from raven.core.task_engine.store import TaskStore
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
        from raven.core.task_engine.runner import TaskRunner
        from raven.core.task_engine.store import TaskStore
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
                "id": s.id,
                "goal": s.goal,
                "status": s.status.value,
                "project_path": s.project_path,
                "files": len(s.files),
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
        await audit_logger.sensitive("shutdown", "api", "system", True)
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
        await audit_logger.log(AuditEventType.COMMAND, "api", "raven", detail={"action": body.action})
        try:
            session = await gateway.db.get_or_create_session(f"vscode:{body.action}:default", "vscode", "vscode_user")
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

    def shutdown_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, shutdown_handler)
        except NotImplementedError:
            logger.debug("Signal handlers not supported on this platform")

    monitor_store = MonitorStore(settings.resolved_db_path)
    monitor_engine = MonitorEngine(monitor_store)
    register_all_monitors(monitor_engine)
    gateway._monitor_engine = monitor_engine
    api_app.state.monitor_engine = monitor_engine

    routine_store = RoutineStore(settings.resolved_db_path)
    routine_engine = RoutineEngine(routine_store)
    register_all_routines(routine_engine)
    api_app.state.routine_engine = routine_engine

    async def run_all():
        await gateway.start()
        await monitor_engine.start()
        await routine_engine.start()
        config = uvicorn.Config(api_app, host="0.0.0.0", port=web_port, log_level="info", ws="auto")  # noqa: S104
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        await stop_event.wait()
        logger.info("Shutting down...")
        shutdown_task = asyncio.create_task(_shutdown(gateway, server_task))
        try:
            await asyncio.wait_for(shutdown_task, timeout=30)
        except TimeoutError:
            logger.warning("Shutdown timed out, forcing exit")
            os._exit(1)

    async def _shutdown(gw: Gateway, sv_task: asyncio.Task[None]):
        for name, coro in [
            ("monitor engine", monitor_engine.stop()),
            ("routine engine", routine_engine.stop()),
            ("LLM cleanup", gw.llm.cleanup()),
            ("gateway stop", gw.stop()),
            ("DB disconnect", gw.db.disconnect()),
            ("client manager", client_manager.close()),
        ]:
            try:
                await asyncio.wait_for(coro, timeout=5)
            except (TimeoutError, ConnectionError, RuntimeError) as e:
                logger.warning("Shutdown {}: {}", name, e)
        try:
            await config_watcher.stop()
        except Exception as e:
            logger.warning("Shutdown config_watcher: {}", e)
        try:
            await audit_logger.stop()
        except Exception as e:
            logger.warning("Shutdown audit_logger: {}", e)
        sv_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sv_task
        logger.info("Shutdown complete")

    try:
        await run_all()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupted, shutting down...")
        try:
            await asyncio.wait_for(gateway.stop(), timeout=10)
        except (TimeoutError, ConnectionError, RuntimeError) as e:
            logger.warning("Interrupt shutdown gateway: {}", e)
        try:
            await asyncio.wait_for(gateway.db.disconnect(), timeout=5)
        except (TimeoutError, ConnectionError, RuntimeError) as e:
            logger.warning("Interrupt shutdown DB: {}", e)
