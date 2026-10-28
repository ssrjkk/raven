from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from loguru import logger

from raven.channels.base import BaseChannel
from raven.core.canvas import canvas_manager
from raven.core.db import Database
from raven.core.llm.queue import PRIORITY_HIGH
from raven.core.models import IncomingMessage, Message
from raven.core.version import __version__
from raven.core.watermark import canary_html_comment, install_fastapi_watermark

_MAX_LINK_PROXY_BYTES = 10 * 1024 * 1024

_HTML_LIKE_MEDIA_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "application/xml",
        "text/xml",
    }
)


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
    except Exception as e:
        logger.debug("[webchat] WS receive timeout/error: {}", e)
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


def _secure_endpoints_enabled() -> bool:
    from raven.core.config import settings

    secret = settings.web_secret_key.get_secret_value() if settings.web_secret_key else ""
    return bool(secret)


async def _authenticate_request(request: Request) -> bool:
    from raven.core.auth.auth_handler import auth_handler
    from raven.core.config import settings

    token = request.headers.get("authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    if not token:
        token = request.query_params.get("token", "")
    if not token:
        return False
    secret = settings.web_secret_key.get_secret_value()
    if secret and hmac.compare_digest(token, secret):
        return True
    try:
        payload = await auth_handler.decode_token(token)
    except Exception as e:
        logger.debug("[webchat] token decode failed: {}", e)
        return False
    return payload is not None


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
        async def list_sessions(request: Request):
            if _secure_endpoints_enabled() and not await _authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})
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
        async def create_session(request: Request):
            if _secure_endpoints_enabled() and not await _authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})
            session_id = f"webchat:{uuid4().hex}:default"
            session = await self._db.get_or_create_session(session_id, "webchat", "web_user")
            return {"id": session.id, "channel": session.channel}

        @app.delete("/api/sessions/{session_id}")
        async def delete_session(session_id: str, request: Request):
            if _secure_endpoints_enabled() and not await _authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})
            await self._db.delete_session(session_id)
            return {"ok": True}

        @app.get("/api/messages/{session_id}")
        async def get_messages(session_id: str, request: Request):
            if _secure_endpoints_enabled() and not await _authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})
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
            await websocket.send_json({"type": "session", "session_id": session_id})
            try:
                while True:
                    data = await websocket.receive_text()
                    try:
                        msg_data = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        await websocket.send_json({"type": "error", "content": "invalid JSON"})
                        continue
                    text = msg_data.get("text", "")
                    candidate = msg_data.get("session_id", "")
                    if isinstance(candidate, str) and candidate.startswith(f"webchat:{client_id}:"):
                        session_id = candidate
                    if text and self._handler:
                        event = IncomingMessage(
                            channel="webchat",
                            user_id=websocket.state.user_id,
                            text=text,
                            session_id=session_id,
                            priority=PRIORITY_HIGH,
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
                    try:
                        msg_data = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        await websocket.send_json({"type": "error", "content": "invalid JSON"})
                        continue
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
                    try:
                        msg = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        await websocket.send_json({"type": "error", "content": "invalid JSON"})
                        continue
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
                        component_id = msg.get("component_id")
                        if not isinstance(component_id, str):
                            await websocket.send_json({"type": "error", "content": "component_id required"})
                            continue
                        session.update_props(component_id, msg.get("props", {}))
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

        @app.get("/api/canvas/image")
        async def canvas_image_proxy(url: str, request: Request) -> Response:
            from raven.core.security.ssrf import safe_fetch_async

            if _secure_endpoints_enabled() and not await _authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})
            if not url.startswith(("http://", "https://")):
                return JSONResponse(status_code=400, content={"error": "Invalid URL scheme"})
            try:
                response = await safe_fetch_async(url, max_bytes=10 * 1024 * 1024)
            except Exception as exc:
                logger.warning("[webchat] canvas image proxy failed: {}", exc)
                return JSONResponse(status_code=502, content={"error": "Proxy failed"})
            return Response(
                content=response.content,
                media_type=response.headers.get("content-type", "application/octet-stream"),
            )

        @app.get("/api/canvas/link")
        async def canvas_link_proxy(url: str, request: Request) -> Response:
            from raven.core.security.ssrf import safe_fetch_async

            if _secure_endpoints_enabled() and not await _authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})
            if not url.startswith(("http://", "https://")):
                return JSONResponse(status_code=400, content={"error": "Invalid URL scheme"})
            try:
                response = await safe_fetch_async(url, max_bytes=_MAX_LINK_PROXY_BYTES)
            except Exception as exc:
                logger.warning("[webchat] canvas link proxy failed: {}", exc)
                return JSONResponse(status_code=502, content={"error": "Proxy failed"})
            content_type = response.headers.get("content-type", "application/octet-stream")
            media_type = content_type.split(";")[0].strip().lower()
            headers = {"X-Content-Type-Options": "nosniff"}
            if media_type in _HTML_LIKE_MEDIA_TYPES:
                headers["Content-Security-Policy"] = "sandbox"
                headers["Referrer-Policy"] = "no-referrer"
            return Response(content=response.content, media_type=content_type, headers=headers)

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
            except Exception as e:
                logger.error("WebChat send_stream failed: {}", e)

    @property
    def app(self) -> FastAPI:
        return self._app

    def _get_index_html(self) -> str:
        built = (
            Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist" / "index.html"
        )
        if built.is_file():
            return built.read_text(encoding="utf-8")
        return INDEX_HTML.replace("__VERSION__", __version__)


# The fallback for a source checkout where `cd web && npm run build` never ran. The React SPA is the
# real UI; this page exists so the gateway is reachable from a browser without Node, and it therefore
# loads nothing from a host other than the one that served it: no CDN, no framework, no floating
# version, and nothing injected into the DOM through innerHTML -- model output is turned into text
# nodes by the small markdown subset below.
#
# It also carries a token. /ws authenticates from `?token=` or a first `{"token": ...}` frame and
# closes 1008 when neither arrives; the page shipped before this one supplied neither, so no message
# ever reached the gateway -- with or without WEB_SECRET_KEY set.
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'">
<!-- frame-ancestors is deliberately absent: it is ignored in a meta element and is set as an
     HTTP header by raven/core/middleware.py, where X-Frame-Options: DENY is also sent -->
<meta name="referrer" content="no-referrer">
<title>Raven AI</title>
<style>
:root {
/* design-tokens:start - generated by scripts/gen_theme_css.py --print-surface, do not edit */
  --dt-colors-bg-primary: #0f1117;
  --dt-colors-bg-secondary: #1a1d2e;
  --dt-colors-border-default: #2a2d3e;
  --dt-colors-border-focus: #8446ee;
  --dt-colors-accent-default: #7c3aed;
  --dt-colors-text-primary: #e4e4e7;
  --dt-colors-text-secondary: #a1a1aa;
  --dt-colors-text-link: #a079f8;
  --dt-colors-text-on-accent: #ffffff;
  --dt-colors-status-success: #22c55e;
  --dt-colors-status-error: #ef4444;
/* design-tokens:end */
  --bg: var(--dt-colors-bg-primary);
  --surface: var(--dt-colors-bg-secondary);
  --line: var(--dt-colors-border-default);
  --focus: var(--dt-colors-border-focus);
  --accent: var(--dt-colors-accent-default);
  --text: var(--dt-colors-text-primary);
  --muted: var(--dt-colors-text-secondary);
  --link: var(--dt-colors-text-link);
  --on-accent: var(--dt-colors-text-on-accent);
  --well: var(--dt-colors-bg-primary);
  --notice: color-mix(in srgb, var(--dt-colors-accent-default) 14%, var(--dt-colors-bg-secondary));
  --bubble: color-mix(in srgb, var(--dt-colors-accent-default) 26%, var(--dt-colors-bg-secondary));
}
* { box-sizing: border-box; }
body { margin: 0; height: 100vh; display: flex; flex-direction: column; background: var(--bg); color: var(--text); font: 14px/1.55 system-ui, -apple-system, sans-serif; }
header { display: flex; align-items: center; gap: .6rem; padding: .75rem 1rem; border-bottom: 1px solid var(--line); background: var(--surface); }
header b { font-size: 1rem; }
header span { color: var(--muted); font-size: .8rem; }
#log { flex: 1; overflow-y: auto; padding: 1rem; display: flex; flex-direction: column; gap: .6rem; }
.msg { max-width: 76%; padding: .6rem .85rem; border-radius: .9rem; white-space: pre-wrap; overflow-wrap: anywhere; }
.msg.user { align-self: flex-end; background: var(--bubble); }
.msg.assistant { align-self: flex-start; background: var(--surface); border: 1px solid var(--line); }
.msg.system { align-self: center; background: transparent; color: var(--muted); font-size: .8rem; padding: 0 .5rem; }
.msg pre { background: var(--well); border: 1px solid var(--line); border-radius: .5rem; padding: .7rem; overflow-x: auto; margin: .4rem 0; }
.msg code { font-family: ui-monospace, "JetBrains Mono", monospace; font-size: .85em; }
.msg p { margin: .3rem 0; }
.msg ul, .msg ol { margin: .3rem 0 .3rem 1.2rem; padding: 0; }
.msg a { color: var(--link); }
.msg.user a { color: var(--text); text-decoration: underline; }
#composer { display: flex; gap: .5rem; padding: .75rem 1rem; border-top: 1px solid var(--line); background: var(--surface); }
#draft { flex: 1; background: var(--well); border: 1px solid var(--line); border-radius: .7rem; color: var(--text); padding: .6rem .8rem; font: inherit; }
#draft:focus { outline: none; border-color: var(--focus); }
button:focus-visible, #token:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
button { background: var(--accent); border: 0; border-radius: .7rem; color: var(--on-accent); font: inherit; padding: .6rem 1.1rem; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
#key { display: flex; flex-wrap: wrap; gap: .5rem; padding: .75rem 1rem; border-bottom: 1px solid var(--line); background: var(--notice); }
#key input { flex: 1; background: var(--well); border: 1px solid var(--line); border-radius: .5rem; color: var(--text); padding: .45rem .6rem; font: inherit; }
[hidden] { display: none !important; }
</style>
</head>
<body>
<header><b>Raven AI</b><span>raven-ai __VERSION__ · no third-party requests</span><span id="state">connecting…</span></header>
<div id="key" hidden>
<input id="token" type="password" placeholder="WEB_SECRET_KEY or a session token" autocomplete="off">
<button id="unlock" type="button">Unlock</button>
</div>
<div id="log"></div>
<form id="composer">
<input id="draft" type="text" placeholder="Type a message…" autocomplete="off" disabled>
<button id="send" type="submit" disabled>Send</button>
</form>
<script>
(function () {
  "use strict";
  var log = document.getElementById("log");
  var state = document.getElementById("state");
  var draft = document.getElementById("draft");
  var sendButton = document.getElementById("send");
  var keyRow = document.getElementById("key");
  var tokenField = document.getElementById("token");
  var token = new URLSearchParams(location.search).get("token") || "";
  var ws = null;
  var sessionId = null;
  var streamRow = null;
  var pendingTools = {};

  function note(text) {
    var row = document.createElement("div");
    row.className = "msg system";
    row.textContent = text;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  }

  function bubble(role) {
    var row = document.createElement("div");
    row.className = "msg " + role;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }

  function mdInline(src, into) {
    var pattern = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\((?:https?:\/\/|\/)[^)\s]+\))/g;
    var last = 0;
    var match;
    while ((match = pattern.exec(src)) !== null) {
      if (match.index > last) into.appendChild(document.createTextNode(src.slice(last, match.index)));
      var chunk = match[0];
      if (chunk.charAt(0) === "*") {
        var strong = chunk.charAt(1) === "*";
        var tag = document.createElement(strong ? "strong" : "em");
        tag.textContent = chunk.slice(strong ? 2 : 1, strong ? -2 : -1);
        into.appendChild(tag);
      } else if (chunk.charAt(0) === "`") {
        var code = document.createElement("code");
        code.textContent = chunk.slice(1, -1);
        into.appendChild(code);
      } else {
        var split = chunk.slice(1, -1).split("](");
        var link = document.createElement("a");
        link.textContent = split[0];
        link.href = split[1];
        link.rel = "noopener noreferrer";
        link.target = "_blank";
        into.appendChild(link);
      }
      last = pattern.lastIndex;
    }
    if (last < src.length) into.appendChild(document.createTextNode(src.slice(last)));
  }

  function render(text, into) {
    var lines = String(text === null || text === undefined ? "" : text).split("\n");
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (/^```/.test(line)) {
        var buf = [];
        i += 1;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i += 1;
        var pre = document.createElement("pre");
        var code = document.createElement("code");
        code.textContent = buf.join("\n");
        pre.appendChild(code);
        into.appendChild(pre);
        continue;
      }
      var heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        var h = document.createElement("h" + Math.min(6, heading[1].length + 3));
        mdInline(heading[2], h);
        into.appendChild(h);
        i += 1;
        continue;
      }
      if (/^\s*[-*+]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
        var ordered = /^\s*\d+\.\s+/.test(line);
        var list = document.createElement(ordered ? "ol" : "ul");
        var bullet = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/;
        while (i < lines.length && bullet.test(lines[i])) {
          var item = document.createElement("li");
          mdInline(lines[i].replace(bullet, ""), item);
          list.appendChild(item);
          i += 1;
        }
        into.appendChild(list);
        continue;
      }
      if (!line.trim()) { i += 1; continue; }
      var para = document.createElement("p");
      var acc = [line];
      i += 1;
      while (i < lines.length && lines[i].trim() && !/^```/.test(lines[i])
        && !/^(#{1,4})\s+/.test(lines[i]) && !/^\s*[-*+]\s+/.test(lines[i]) && !/^\s*\d+\.\s+/.test(lines[i])) {
        acc.push(lines[i]);
        i += 1;
      }
      mdInline(acc.join("\n"), para);
      into.appendChild(para);
    }
  }

  function ready(isReady) {
    draft.disabled = !isReady;
    sendButton.disabled = !isReady;
    state.textContent = isReady ? "connected" : state.textContent;
  }

  function authUrl(path) {
    return path + (path.indexOf("?") === -1 ? "?" : "&") + "token=" + encodeURIComponent(token);
  }

  function loadHistory() {
    if (!sessionId || !token) return;
    fetch(authUrl("/api/messages/" + encodeURIComponent(sessionId)))
      .then(function (res) { return res.ok ? res.json() : []; })
      .then(function (rows) {
        if (!Array.isArray(rows) || !rows.length) return;
        log.textContent = "";
        rows.forEach(function (row) {
          var body = bubble(row.role === "user" ? "user" : "assistant");
          render(row.content, body);
        });
      })
      .catch(function () { /* history is a convenience; the conversation works without it */ });
  }

  function connect() {
    if (!token) {
      state.textContent = "key required";
      keyRow.hidden = false;
      return;
    }
    state.textContent = "connecting…";
    // ?token= because a browser WebSocket cannot set an Authorization header; the gateway logs the
    // path without the query, so the secret never reaches an access log
    ws = new WebSocket((location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host + "/ws?token=" + encodeURIComponent(token));
    ws.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.type === "session") {
        sessionId = data.session_id;
        ready(true);
        loadHistory();
      } else if (data.type === "stream") {
        if (!streamRow) streamRow = bubble("assistant");
        streamRow.textContent += data.content || "";
        log.scrollTop = log.scrollHeight;
      } else if (data.type === "message") {
        var body = streamRow || bubble("assistant");
        body.textContent = "";
        render(data.content, body);
        streamRow = null;
      } else if (data.type === "tool_call") {
        var name = (data.data && data.data.name) || "tool";
        pendingTools[name] = true;
        note(name + " → running");
      } else if (data.type === "tool_result") {
        note(((data.data && data.data.name) || "tool") + " → done");
      } else if (data.type === "error") {
        note("error: " + (data.content || "unknown"));
      } else if (data.type === "done" || data.type === "step_start") {
        if (data.type === "done") { streamRow = null; pendingTools = {}; }
      }
    };
    ws.onclose = function () {
      ready(false);
      state.textContent = "disconnected — retrying";
      setTimeout(connect, 1500);
    };
    ws.onerror = function () { ws.close(); };
  }

  document.getElementById("unlock").addEventListener("click", function () {
    token = tokenField.value.trim();
    keyRow.hidden = true;
    if (token) connect();
  });
  document.getElementById("composer").addEventListener("submit", function (event) {
    event.preventDefault();
    var text = draft.value;
    if (!text.trim() || !ws || ws.readyState !== 1) return;
    var mine = bubble("user");
    render(text, mine);
    ws.send(JSON.stringify({ text: text, session_id: sessionId || "" }));
    draft.value = "";
  });

  if (token) connect(); else { keyRow.hidden = false; state.textContent = "key required"; }
})();
</script>
</body>
</html>"""
