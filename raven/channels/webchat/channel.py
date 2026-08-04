from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger

from raven.channels.base import BaseChannel
from raven.core.canvas import canvas_manager
from raven.core.db import Database
from raven.core.models import IncomingMessage, Message
from raven.core.watermark import canary_html_comment, install_fastapi_watermark


async def _validate_ws_token(token: str) -> dict[str, Any] | None:
    from raven.core.auth.auth_handler import auth_handler
    from raven.core.config import settings

    secret = settings.web_secret_key.get_secret_value()
    if secret and hmac.compare_digest(token, secret):
        return {"sub": "admin", "role": "admin"}
    try:
        return await auth_handler.decode_token(token)
    except Exception as e:
        logger.debug("[webchat] WS token decode failed: {}", e)
        return None


async def _authenticate_ws(websocket: WebSocket) -> dict[str, Any] | None:
    query_token = websocket.query_params.get("token", "")
    if query_token:
        payload = await _validate_ws_token(query_token)
        if payload is None:
            await websocket.close(code=1008, reason="Authentication required")
            return None
        await websocket.accept()
        return payload

    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
    except Exception:
        await websocket.close(code=1008, reason="Authentication required")
        return None
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        await websocket.close(code=1008, reason="Authentication required")
        return None
    token = str(msg.get("token", "")) if isinstance(msg, dict) else ""
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return None
    payload = await _validate_ws_token(token)
    if payload is None:
        await websocket.close(code=1008, reason="Authentication required")
        return None
    return payload


class WebChatChannel(BaseChannel):
    channel_id = "webchat"

    def __init__(self, db: Database) -> None:
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._db = db
        self._app = FastAPI(title="Raven AI Web Chat")
        self._connections: dict[str, WebSocket] = {}
        self._ready = False
        install_fastapi_watermark(self._app)
        self._setup_routes()

    def _setup_routes(self) -> None:
        app = self._app

        @app.get("/")
        async def get_index():
            html = self._get_index_html()
            html = html.replace("</head>", f"{canary_html_comment()}\n</head>")
            return HTMLResponse(html)

        @app.get("/api/sessions")
        async def list_sessions():
            sessions = await self._db.get_sessions()
            return [
                {
                    "id": s.id,
                    "channel": s.channel,
                    "user_id": s.user_id,
                    "agent_id": s.agent_id,
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in sessions
            ]

        @app.post("/api/sessions")
        async def create_session():
            session_id = f"webchat:{uuid4().hex}:default"
            session = await self._db.get_or_create_session(session_id, "webchat", "web_user")
            return {"id": session.id, "channel": session.channel}

        @app.delete("/api/sessions/{session_id}")
        async def delete_session(session_id: str):
            await self._db.delete_session(session_id)
            return {"ok": True}

        @app.get("/api/messages/{session_id}")
        async def get_messages(session_id: str):
            msgs = await self._db.get_session_messages(session_id, limit=50)
            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in msgs
            ]

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            payload = await _authenticate_ws(websocket)
            if payload is None:
                return
            websocket.state.user_id = payload.get("sub", "unknown")
            websocket.state.role = payload.get("role", "user")
            client_id = str(uuid4().hex[:8])
            self._connections[client_id] = websocket
            session_id = f"webchat:{client_id}:default"
            try:
                while True:
                    data = await websocket.receive_text()
                    msg_data = json.loads(data)
                    text = msg_data.get("text", "")
                    session_id = msg_data.get("session_id", session_id)
                    if text and self._handler:
                        event = IncomingMessage(
                            channel="webchat",
                            user_id=websocket.state.user_id,
                            text=text,
                            session_id=session_id,
                        )
                        await self._handler(event)
                    elif text and not self._handler:
                        logger.warning("[webchat] no handler registered, dropping message")
            except WebSocketDisconnect:
                logger.debug("[webchat] client disconnected")
            finally:
                self._connections.pop(client_id, None)

        @app.websocket("/ws/stream")
        async def agent_stream(websocket: WebSocket):
            payload = await _authenticate_ws(websocket)
            if payload is None:
                return
            client_id = str(uuid4().hex[:8])
            session_id = f"webchat:{client_id}:stream"
            from raven.channels.webchat.streaming import AgentStreamHandler

            handler = AgentStreamHandler(websocket, session_id)
            try:
                while True:
                    data = await websocket.receive_text()
                    msg_data = json.loads(data)
                    text = msg_data.get("text", "")
                    if text:
                        await handler.handle_message(text)
            except WebSocketDisconnect:
                logger.debug("[webchat] stream client disconnected")
            except Exception as exc:
                logger.warning("[webchat] stream error: {}", exc)

        @app.websocket("/ws/canvas")
        async def canvas_websocket(websocket: WebSocket):
            payload = await _authenticate_ws(websocket)
            if payload is None:
                return
            session = canvas_manager.create_session(str(uuid4().hex[:12]))
            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    action = msg.get("action", "")
                    if action == "render":
                        from raven.core.canvas import CanvasComponent

                        comp_data = msg.get("component", {})
                        if comp_data:

                            def _from_dict(d):
                                c = CanvasComponent(d["type"], d.get("props"))
                                for child in d.get("children", []):
                                    c.add_child(_from_dict(child))
                                return c

                            comp = _from_dict(comp_data)
                            session.render(comp)
                            await websocket.send_json({"type": "canvas_rendered", "session_id": session.session_id})
                    elif action == "update_props":
                        session.update_props(msg["component_id"], msg.get("props", {}))
                        await websocket.send_json({"type": "props_updated"})
                    elif action == "action":
                        result = canvas_manager.handle_action(
                            session.session_id,
                            msg.get("component_id", ""),
                            msg.get("action_name", ""),
                            msg.get("data"),
                        )
                        await websocket.send_json({"type": "action_result", "result": result})
                    elif action == "get_state":
                        await websocket.send_json({"type": "canvas_state", **session.to_dict()})
                    elif action == "list_sessions":
                        await websocket.send_json({"type": "session_list", "sessions": canvas_manager.list_sessions()})
            except WebSocketDisconnect:
                logger.debug("[webchat] canvas client disconnected")
            finally:
                canvas_manager.delete_session(session.session_id)

    async def start(self):
        self._ready = True
        logger.info("WebChat channel ready")

    async def stop(self):
        for ws in list(self._connections.values()):
            with contextlib.suppress(ConnectionError, RuntimeError):
                await ws.close()
        self._connections.clear()
        self._ready = False

    async def connect(self):
        if not self._ready:
            await self.start()

    async def disconnect(self):
        await self.stop()

    async def health_check(self) -> bool:
        return self._ready

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def send(self, session_id: str, message: Message):
        parts = session_id.split(":")
        client_id = parts[1] if len(parts) >= 2 else None
        if client_id and client_id in self._connections:
            try:
                await self._connections[client_id].send_json(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": message.content,
                        "session_id": session_id,
                    }
                )
            except Exception as e:
                logger.error("WebChat send failed: {}", e)

    async def send_stream(self, session_id: str, text: str) -> None:
        parts = session_id.split(":")
        client_id = parts[1] if len(parts) >= 2 else None
        if client_id and client_id in self._connections:
            try:
                if text.startswith("{") and text.endswith("}"):
                    import json as _json

                    parsed = _json.loads(text)
                    parsed["session_id"] = session_id
                    await self._connections[client_id].send_json(parsed)
                else:
                    await self._connections[client_id].send_json(
                        {
                            "type": "stream",
                            "content": text,
                            "session_id": session_id,
                        }
                    )
            except (json.JSONDecodeError, Exception) as e:
                logger.error("WebChat send_stream failed: {}", e)

    @property
    def app(self) -> FastAPI:
        return self._app

    def _get_index_html(self) -> str:
        return INDEX_HTML


INDEX_HTML = """<!DOCTYPE html>
<!--
  The full React + Vite web UI is available at raven-ai/web/
  Build: cd web && npm install && npm run build
  The FastAPI server serves this minimal Alpine.js version as fallback.
-->
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Raven AI</title>
<script src="https://cdn.tailwindcss.com"></script>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root { --bg: #1a1a2e; --surface: #16213e; --accent: #0f3460; --text: #e4e4e7; --secondary: #a1a1aa; }
body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; }
.sidebar { background: var(--surface); border-right: 1px solid #2a2a4a; }
.chat-area { background: var(--bg); }
.message { max-width: 80%; margin-bottom: 0.75rem; line-height: 1.5; }
.message.user { background: var(--accent); color: white; border-radius: 1rem 1rem 0.25rem 1rem; padding: 0.75rem 1rem; }
.message.assistant { background: var(--surface); border: 1px solid #2a2a4a;
  border-radius: 1rem 1rem 1rem 0.25rem; padding: 0.75rem 1rem; }
.message.system { background: #2d1b4e; border: 1px solid #4a2d6e;
  border-radius: 0.5rem; padding: 0.5rem 0.75rem; font-size: 0.875rem; color: #c4a0e0; }
.input-area { background: var(--surface); border-top: 1px solid #2a2a4a; }
input { background: #1e1e3a; border: 1px solid #2a2a4a; color: var(--text); }
input:focus { outline: none; border-color: var(--accent); }
.channel-indicator { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.channel-telegram { background: #0088cc; }
.channel-discord { background: #5865F2; }
.channel-webchat { background: #22c55e; }
pre { background: #0d0d1a; border-radius: 0.5rem; padding: 1rem; overflow-x: auto; margin: 0.5rem 0; }
code { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.875rem; }
p code { background: #0d0d1a; padding: 0.125rem 0.375rem; border-radius: 0.25rem; }
.typing::after { content: '...'; animation: dots 1.5s infinite; }
@keyframes dots { 0%,20% { content: '.'; } 40% { content: '..'; } 60%,100% { content: '...'; } }
</style>
</head>
<body class="h-screen flex overflow-hidden" x-data="app()">
<div class="sidebar w-72 flex-shrink-0 flex flex-col h-full">
<div class="p-4 border-b border-gray-700/50">
<h1 class="text-xl font-bold flex items-center gap-2">
<span class="text-2xl">🐦</span> Raven AI
</h1>
</div>
<div class="flex-1 overflow-y-auto p-2 space-y-1">
<div class="text-xs text-gray-500 uppercase tracking-wider px-2 py-2">Sessions</div>
<template x-for="session in sessions" :key="session.id">
<div class="flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer hover:bg-white/5 transition"
:class="{'bg-white/10': session.id === currentSession}"
@click="switchSession(session.id)">
<span class="channel-indicator" :class="'channel-' + session.channel"></span>
<span class="text-sm truncate flex-1" x-text="session.id.split(':').slice(0,2).join(' ').slice(-20)"></span>
<span class="text-xs text-gray-500" x-text="new Date(session.updated_at).toLocaleDateString()"></span>
</div>
</template>
</div>
<div class="p-3 border-t border-gray-700/50 text-xs text-gray-500 text-center">
raven-ai v0.1.0
</div>
</div>
<div class="flex-1 flex flex-col h-full chat-area">
<div class="flex-1 overflow-y-auto p-4 space-y-1" id="messages-container">
<template x-for="msg in messages" :key="msg.id">
<div class="flex" :class="msg.role === 'user' ? 'justify-end' : 'justify-start'">
<div class="message" :class="msg.role">
                    <div x-html="renderContent(msg.content)"></div>
                </div>
</div>
</template>
<div x-show="isLoading" class="message assistant" style="max-width:80%">
            <span class="typing"></span>
<div x-show="streamingEvent" class="message assistant streaming-event"
  style="max-width:80%" x-html="streamingEvent"></div>
<div x-show="streamingToolCalls.length > 0" class="message system" style="max-width:80%">
<template x-for="tc in streamingToolCalls" :key="tc.id">
<div class="text-xs"><span x-text="tc.name"></span> <span x-text="tc.status"></span></div>
</template>
</div>
</div>
</div>
<div class="input-area p-4">
<form @submit.prevent="sendMessage()" class="flex gap-2">
<input type="text" x-model="inputText" placeholder="Type a message..."
  class="flex-1 rounded-xl px-4 py-3 text-sm" @keydown.enter.prevent="sendMessage()">
<button type="submit"
  class="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-xl text-sm font-medium transition">Send</button>
</form>
</div>
</div>
<script>
function app() {
return {
sessions: [],
messages: [],
currentSession: null,
inputText: '',
ws: null,
isLoading: false,
streamingEvent: '',
streamingToolCalls: [],
useStream: true,
init() {
this.loadSessions();
this.connectWs();
},
async loadSessions() {
const res = await fetch('/api/sessions');
this.sessions = await res.json();
if (this.sessions.length > 0) {
this.currentSession = this.sessions[0].id;
this.loadMessages();
}
},
async loadMessages() {
if (!this.currentSession) return;
const res = await fetch(`/api/messages/${this.currentSession}`);
this.messages = await res.json();
this.$nextTick(() => this.scrollDown());
},
connectWs() {
const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
this.ws = new WebSocket(`${protocol}//${location.host}/ws`);
this.ws.onmessage = (e) => {
const data = JSON.parse(e.data);
if (data.type === 'message') {
this.messages.push({ id: Date.now(), role: data.role, content: data.content, created_at: new Date().toISOString() });
this.isLoading = false;
this.$nextTick(() => this.scrollDown());
} else if (data.type === 'step_start') {
this.streamingEvent = '<em>thinking...</em>';
this.isLoading = true;
} else if (data.type === 'tool_call') {
const tc = { id: Date.now(), name: data.data.name, status: 'running' };
this.streamingToolCalls.push(tc);
this.streamingEvent = '<em>running tool: ' + data.data.name + '</em>';
} else if (data.type === 'tool_result') {
const tc = this.streamingToolCalls.find(t => t.name === data.data.name);
if (tc) tc.status = 'done';
} else if (data.type === 'done') {
this.streamingToolCalls = [];
this.streamingEvent = '';
this.isLoading = false;
}
};
this.ws.onclose = () => setTimeout(() => this.connectWs(), 1000);
},
async sendMessage() {
if (!this.inputText.trim() || this.isLoading) return;
this.isLoading = true;
const sessionId = this.currentSession || 'webchat:anon:default';
this.messages.push({ id: Date.now(), role: 'user', content: this.inputText, created_at: new Date().toISOString() });
if (this.useStream) {
this.ws.send(JSON.stringify({ text: this.inputText, session_id: sessionId }));
} else {
this.ws.send(JSON.stringify({ text: this.inputText, session_id: sessionId }));
}
this.inputText = '';
this.$nextTick(() => this.scrollDown());
},
switchSession(id) {
this.currentSession = id;
this.loadMessages();
},
renderContent(content) {
try { return marked.parse(content); } catch(e) { return content; }
},
scrollDown() {
const container = document.getElementById('messages-container');
if (container) container.scrollTop = container.scrollHeight;
}
}
}
</script>
</body>
</html>"""
