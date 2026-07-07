from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger


class MCPClientError(Exception):
    pass


class MCPClient:
    def __init__(self, command: list[str], cwd: str | Path | None = None):
        self._command = command
        self._cwd = Path(cwd) if cwd else None
        self._process: asyncio.subprocess.Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._req_id = 0
        self._tools: list[dict[str, Any]] | None = None
        self._server_info: dict[str, Any] | None = None

    async def connect(self) -> None:
        logger.info("Connecting to MCP server: {}", " ".join(self._command))
        self._process = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._cwd,
        )
        self._writer = self._process.stdin
        self._reader = self._process.stdout

        result = await self._send_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "raven-mcp-client", "version": "0.4.0"},
        })
        self._server_info = result.get("serverInfo", {})
        logger.info("MCP server connected: {}", self._server_info)

        try:
            self._tools = await self.list_tools()
        except Exception as exc:
            await self.disconnect()
            raise MCPClientError(f"Connected but failed to list tools: {exc}") from exc

    async def disconnect(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
            logger.info("MCP server disconnected")

    @property
    def tools(self) -> list[dict[str, Any]]:
        if self._tools is None:
            return []
        return self._tools

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])  # type: ignore[no-any-return]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        return result.get("content", [])

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._writer or not self._reader:
            raise MCPClientError("Not connected to MCP server")

        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }

        line = json.dumps(request, ensure_ascii=False) + "\n"
        self._writer.write(line.encode("utf-8"))
        await self._writer.drain()

        raw = b""
        while True:
            chunk = await asyncio.wait_for(self._reader.readline(), timeout=30)
            if not chunk:
                raise MCPClientError("MCP server closed connection")
            raw += chunk
            try:
                response = json.loads(raw.decode("utf-8").strip())
                break
            except json.JSONDecodeError:
                continue

        if "error" in response:
            err = response["error"]
            raise MCPClientError(f"MCP error {err.get('code', '?')}: {err.get('message', 'unknown')}")

        return response.get("result", {})  # type: ignore[no-any-return]

    def to_llm_tools(self) -> list[dict[str, Any]]:
        tools = self._tools or []
        return [
            {
                "type": "function",
                "function": {
                    "name": f"mcp_{tool.get('name', 'unknown')}",
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema") or tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
            for tool in tools
        ]


class MCPClientPool:
    def __init__(self):
        self._clients: dict[str, MCPClient] = {}

    async def connect(self, name: str, command: list[str], cwd: str | Path | None = None) -> MCPClient:
        client = MCPClient(command, cwd=cwd)
        await client.connect()
        self._clients[name] = client
        logger.info("MCP client '{}' connected with {} tools", name, len(client.tools))
        return client

    async def disconnect_all(self) -> None:
        for name, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting MCP client '{}': {}", name, exc)
        self._clients.clear()

    def get_client(self, name: str) -> MCPClient | None:
        return self._clients.get(name)

    @property
    def connected_count(self) -> int:
        return len(self._clients)

    def all_tools(self) -> list[dict[str, Any]]:
        tools = []
        for name, client in self._clients.items():
            for tool in client.tools:
                prefixed = dict(tool)
                prefixed["name"] = f"mcp_{name}_{tool.get('name', 'unknown')}"
                tools.append(prefixed)
        return tools


_client_pool = MCPClientPool()


def get_mcp_pool() -> MCPClientPool:
    return _client_pool
