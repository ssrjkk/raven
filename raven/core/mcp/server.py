from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from typing import Any

from ravencode.runtime.tools import execute_tool_public, get_tool_definitions


def use_utf8_stdio() -> None:
    """Pin the stdio transport to UTF-8, the only encoding the MCP spec allows on the wire.

    Left alone, `sys.stdin`/`sys.stdout` inherit this machine's ANSI code page (cp1251 on a
    Russian Windows, ascii under a POSIX C locale), so a host's UTF-8 frames arrive decoded into
    the wrong string and any result the code page cannot encode raises UnicodeEncodeError inside
    `_send_response`, which ended the session with a traceback.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def _to_mcp_tool(defn: dict[str, Any]) -> dict[str, Any]:
    fn = defn.get("function", defn)
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "inputSchema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


class MCPServer:
    server_name: str = "raven-mcp"
    server_version: str = "0.4.8"

    def __init__(self) -> None:
        self._running = False

    async def _send_response(self, msg: dict[str, Any]) -> None:
        text = json.dumps(msg, ensure_ascii=False)
        sys.stdout.write(text + "\n")
        await asyncio.to_thread(sys.stdout.flush)

    async def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {})

        # JSON-RPC notifications carry no id and must not get a response.
        if method.startswith("notifications/"):
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": self.server_name, "version": self.server_version},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "logging/setLevel":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            tools = [_to_mcp_tool(d) for d in get_tool_definitions()]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})
            if not name:
                return _error(req_id, -32602, "Missing tool name")
            result = await execute_tool_public(name, args)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result}]}}
        return _error(req_id, -32601, f"Method not found: {method}")

    async def run(self) -> None:
        """Serve newline-delimited JSON-RPC over stdin until the client closes it."""
        self._running = True
        while self._running:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                return
            line = line.strip()
            # Framing, not a message: a host that writes an empty line keeps its session alive.
            if not line:
                continue
            try:
                req: Any = json.loads(line)
            except json.JSONDecodeError:
                await self._send_response(_error(None, -32700, "Parse error"))
                continue
            if not isinstance(req, dict):
                await self._send_response(_error(None, -32600, "Invalid request: expected a JSON object"))
                continue
            resp = await self.handle_request(req)
            if resp is not None:
                await self._send_response(resp)

    def stop(self) -> None:
        self._running = False


async def run_mcp_server() -> None:
    server = MCPServer()
    await server.run()
