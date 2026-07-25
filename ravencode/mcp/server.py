"""MCP (Model Context Protocol) server for ravencode.

Implements the Model Context Protocol over stdio,
exposing ravencode tools for MCP-compatible clients.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from ravencode.runtime.tools import execute_tool, get_tool_definitions


class MCPServer:
    def __init__(self) -> None:
        self._running = False

    async def _read_request(self) -> dict[str, Any] | None:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            return None
        line = line.strip()
        if not line:
            return None
        try:
            data: Any = json.loads(line)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def _send_response(self, msg: dict[str, Any]) -> None:
        text = json.dumps(msg, ensure_ascii=False)
        sys.stdout.write(text + "\n")
        await asyncio.to_thread(sys.stdout.flush)

    async def handle_request(self, req: dict[str, Any]) -> dict[str, Any]:
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "ravencode", "version": "0.4.0"},
                },
            }
        if method == "tools/list":
            tools = get_tool_definitions()
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments", {})
            result = await execute_tool(name, args)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": result}]}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    async def run(self) -> None:
        self._running = True
        while self._running:
            req = await self._read_request()
            if req is None:
                break
            resp = await self.handle_request(req)
            await self._send_response(resp)

    def stop(self) -> None:
        self._running = False


async def run_mcp_server() -> None:
    server = MCPServer()
    await server.run()
