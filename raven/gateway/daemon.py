from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from raven.core._json import json
from raven.core.auth.auth_handler import auth_handler
from raven.core.channel_guardian import TokenBucket
from raven.core.config import settings
from raven.core.llm import LLMRouter
from raven.core.logging import setup_logging
from raven.core.sse import sse_stream
from raven.gateway.routing import RoutingEngine
from raven.gateway.session_store import SessionStore
from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.multisession import get_session_manager
from ravencode.runtime.tools import execute_tool, get_tool_definitions

_SESSION_TTL_SECONDS = 300
_FLUSH_INTERVAL_SECONDS = 5


class AgentRequest(BaseModel):
    message: str
    channel: str = "default"
    session_id: str = ""
    mode: str = "build"
    max_steps: int = 30


class SessionInfo(BaseModel):
    id: str
    channel: str
    created_at: str
    message_count: int
    status: str


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    dangerous: bool = False


@dataclass
class FlowSession:
    id: str
    channel: str
    created_at: str
    agent: ReActAgent | None = None
    message_count: int = 0
    status: str = "idle"
    _task: asyncio.Task[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "channel": self.channel,
            "created_at": self.created_at,
            "message_count": self.message_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowSession | None:
        session_id = data.get("id")
        if not isinstance(session_id, str) or not session_id:
            return None
        return cls(
            id=session_id,
            channel=str(data.get("channel", "default")),
            created_at=str(data.get("created_at", datetime.now(UTC).isoformat())),
            message_count=max(0, int(data.get("message_count", 0) or 0)),
            status=str(data.get("status", "idle")),
        )


async def _validate_token(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        return await auth_handler.decode_token(token)
    except Exception as e:
        logger.debug("Token validation failed: {}", e)
        return None


class RavenFlowDaemon:
    def __init__(self, port: int = 18789, data_dir: Path | None = None):
        self.port = port
        self.app = FastAPI(title="RavenFlow Gateway", version="1.0.0")
        self.sessions: dict[str, FlowSession] = {}
        self.llm = LLMRouter()
        self.routing = RoutingEngine()
        self._lock = asyncio.Lock()
        self._agent_bucket = TokenBucket(rate=10.0)
        base_dir = data_dir if data_dir is not None else settings.resolved_db_path.parent
        self._store = SessionStore(base_dir)
        self._dirty: set[str] = set()
        self._flush_task: asyncio.Task[Any] | None = None
        self._sse = sse_stream
        self._setup_routes()

    def _setup_routes(self) -> None:
        app = self.app

        @app.middleware("http")
        async def auth_and_request_id_middleware(request: Request, call_next):
            request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
            request.state.request_id = request_id

            if request.url.path != "/health":
                auth_header = request.headers.get("Authorization", "")
                token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
                payload = await _validate_token(token)
                if payload is None:
                    return JSONResponse(
                        status_code=401,
                        content={"error": "Authentication required or invalid token"},
                    )
                request.state.user_id = payload.get("sub", "anonymous")
                request.state.role = payload.get("role", "user")

            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        @app.get("/health")
        async def health():
            return {"status": "ok", "service": "ravenflow", "sessions": len(self.sessions)}

        @app.post("/api/agent")
        async def send_to_agent(req: AgentRequest):
            if not await self._agent_bucket.acquire():
                return {"error": "Rate limit exceeded", "session_id": ""}
            session = await self._get_or_create_session(req.session_id or str(uuid.uuid4())[:8], req.channel, req.mode)
            if session.agent is None:
                return {"error": "agent not initialized", "session_id": session.id}
            if req.mode == "plan":
                session.agent.config.plan_mode = True
                session.agent.config.confirm_dangerous = False
            session.status = "running"
            session.message_count += 1
            self._mark_dirty(session.id)
            await self._publish_session(session, "updated")
            try:
                result = await session.agent.run(req.message)
                session.status = "idle"
                self._mark_dirty(session.id)
                await self._publish_session(session, "updated")
                return {"response": result[:5000], "session_id": session.id}
            except Exception as exc:
                session.status = "idle"
                self._mark_dirty(session.id)
                await self._publish_session(session, "updated")
                logger.error("Agent run failed: {}", exc)
                return {"error": "Agent execution failed", "session_id": session.id}

        @app.get("/api/sessions")
        async def list_sessions():
            mgr = get_session_manager()
            return {
                "sessions": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "status": s.status,
                        "agent_type": s.agent_type,
                        "created_at": s.created_at,
                        "message_count": s.message_count,
                        "step_count": s.step_count,
                    }
                    for s in mgr.sessions
                ],
                "flow_sessions": [
                    {"id": s.id, "channel": s.channel, "status": s.status, "messages": s.message_count}
                    for s in self.sessions.values()
                ],
            }

        @app.get("/api/tools")
        async def list_tools():
            defs = get_tool_definitions()
            return {
                "tools": [{"name": t["function"]["name"], "description": t["function"]["description"]} for t in defs]
            }

        @app.post("/api/tools/{name}")
        async def execute_tool_endpoint(name: str, args: dict[str, Any]):
            result = await execute_tool(name, args)
            return {"result": result[:5000]}

        @app.post("/api/sandbox")
        async def run_sandbox(code: str, language: str = "python"):
            from ravencode.runtime.sandbox import get_sandbox

            result = await get_sandbox().run_code(code, language)
            return {"result": result[:5000]}

        @app.get("/api/routing")
        async def get_routing():
            return {"rules": self.routing.list_rules()}

        @app.post("/api/routing")
        async def add_routing(pattern: str, agent_id: str):
            self.routing.add_rule(pattern, agent_id)
            return {"ok": True, "pattern": pattern, "agent_id": agent_id}

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            token = ws.query_params.get("token", "")
            payload = await _validate_token(token)
            if payload is None:
                await ws.close(code=1008, reason="Authentication required")
                return
            ws.state.user_id = payload.get("sub", "anonymous")
            ws.state.role = payload.get("role", "user")
            logger.debug("WebSocket authenticated: user_id={}", ws.state.user_id)

            await ws.accept()
            logger.info("RavenFlow WebSocket connected (user={})", ws.state.user_id)
            try:
                while True:
                    data = await ws.receive_text()
                    msg = json.loads(data)
                    msg_type = msg.get("type", "message")
                    if msg_type == "message":
                        session = await self._get_or_create_session(
                            msg.get("session_id", str(uuid.uuid4())[:8]),
                            msg.get("channel", "websocket"),
                            msg.get("mode", "build"),
                        )
                        if session.agent is None:
                            await ws.send_text(json.dumps({"type": "error", "content": "agent not initialized"}))
                            continue
                        result = await session.agent.run(msg.get("content", ""))
                        session.message_count += 1
                        self._mark_dirty(session.id)
                        await self._publish_session(session, "updated")
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "response",
                                    "content": result[:5000],
                                    "session_id": session.id,
                                }
                            )
                        )
                    elif msg_type == "ping":
                        await ws.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                logger.info("RavenFlow WebSocket disconnected")
            except Exception as exc:
                logger.exception("RavenFlow WebSocket error: {}", exc)

    async def _get_or_create_session(self, session_id: str, channel: str, mode: str = "build") -> FlowSession:
        async with self._lock:
            session = self.sessions.get(session_id)
            if session is not None:
                if session.agent is None:
                    session.agent = self._build_agent(channel, mode)
                    logger.info("RavenFlow session resumed with fresh agent: {} ({})", session_id, channel)
                return session
            agent = self._build_agent(channel, mode)
            session = FlowSession(
                id=session_id,
                channel=channel,
                created_at=datetime.now(UTC).isoformat(),
                agent=agent,
            )
            self.sessions[session_id] = session
            self._mark_dirty(session_id)
            await self._publish_session(session, "created")
            logger.info("RavenFlow session created: {} ({})", session_id, channel)
            return session

    def _build_agent(self, channel: str, mode: str) -> ReActAgent:
        conv = Conversation(system_prompt=_build_flow_prompt(channel, mode))
        config = AgentConfig(
            max_steps=30,
            confirm_dangerous=(mode == "plan"),
            plan_mode=(mode == "plan"),
        )
        return ReActAgent(config=config, conversation=conv, name=f"ravenflow-{channel}")

    def _mark_dirty(self, session_id: str) -> None:
        self._dirty.add(session_id)

    async def _publish_session(self, session: FlowSession, action: str) -> None:
        await self._sse.broadcast("session", {"action": action, "session": session.to_dict()})

    async def _flush_dirty(self) -> None:
        if not self._dirty:
            return
        dirty = self._dirty
        self._dirty = set()
        for session_id in dirty:
            session = self.sessions.get(session_id)
            if session is None:
                self._store.remove(session_id)
                continue
            try:
                self._store.save(session)
            except Exception as exc:
                logger.error("SessionStore: failed to save {}: {}", session_id, exc)

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_FLUSH_INTERVAL_SECONDS)
                await self._flush_dirty()
        except asyncio.CancelledError:
            await self._flush_dirty()
            raise

    def _load_persisted_sessions(self) -> None:
        try:
            pruned = self._store.prune(_SESSION_TTL_SECONDS)
            if pruned:
                logger.info("SessionStore: pruned {} stale session(s)", pruned)
            for session in self._store.load_all():
                if session.id in self.sessions:
                    continue
                session.status = "resumed"
                self.sessions[session.id] = session
                logger.info("RavenFlow session restored: {} ({}, {} msgs)", session.id, session.channel, session.message_count)
        except Exception as exc:
            logger.error("SessionStore: failed to load persisted sessions: {}", exc)

    async def start(self) -> None:
        import uvloop

        uvloop.install()
        setup_logging()
        import uvicorn

        self._load_persisted_sessions()
        logger.warning("Binding to 0.0.0.0:{}. Ensure firewall/reverse proxy is configured.", self.port)
        config = uvicorn.Config(self.app, host="0.0.0.0", port=self.port, log_level="info")
        server = uvicorn.Server(config)
        logger.info("RavenFlow Gateway starting on port {}", self.port)
        self._flush_task = asyncio.create_task(self._flush_loop())
        try:
            await server.serve()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("RavenFlow Gateway shutdown requested, flushing sessions")
        finally:
            if self._flush_task is not None:
                self._flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(self._flush_task, timeout=_FLUSH_INTERVAL_SECONDS)
            self._flush_task = None
            await self._flush_dirty()

    async def stop(self) -> None:
        for s in self.sessions.values():
            if s.agent:
                s.agent.abort()
        if self._flush_task is not None:
            self._flush_task.cancel()
            self._flush_task = None
        await self._flush_dirty()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="RavenFlow Gateway daemon")
    parser.add_argument("--port", type=int, default=18789, help="Gateway port")
    args = parser.parse_args()

    daemon = RavenFlowDaemon(port=args.port)
    asyncio.run(daemon.start())


def _build_flow_prompt(channel: str, mode: str) -> str:
    mode_instructions = {
        "build": "You have full access to all tools.",
        "plan": "You are in READ-ONLY mode. Do not make changes.",
        "general": "You are a general-purpose assistant for complex tasks.",
    }
    return (
        f"You are RavenFlow, an AI workflow assistant.\n"
        f"Channel: {channel}\n"
        f"Mode: {mode}\n"
        f"{mode_instructions.get(mode, '')}\n\n"
        f"You have tools for web search, file operations, git, shell commands, "
        f"browser automation, and task delegation."
    )
