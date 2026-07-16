from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.config import settings
from raven.core.mcp.channel_bridge import ChannelBridge
from raven.core.mcp.mcp_client import MCPClientPool

if TYPE_CHECKING:
    from raven.core.plugin_loader import PluginLoader

SendMessageFn = Any


class MCPBridge:
    def __init__(self, send_fn: SendMessageFn | None = None):
        self.pool = MCPClientPool()
        self.channel_bridge = ChannelBridge(send_fn=send_fn)

    async def start(self, plugin_loader: PluginLoader | None = None) -> None:
        raw = settings.mcp_servers
        if not raw:
            return
        try:
            servers = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse mcp_servers config: {}", exc)
            return
        for name, cfg in servers.items():
            command = cfg.get("command", [])
            cwd = cfg.get("cwd")
            if not command:
                logger.warning("MCP server '{}' has no command, skipping", name)
                continue
            try:
                client = await self.pool.connect(name, command, cwd=cwd)
                if plugin_loader is not None:
                    from raven.core.models import PluginTool

                    for tool in client.tools:
                        raw_name = tool.get("name", "unknown")
                        wrapped = f"mcp_{name}_{raw_name}"
                        params = tool.get("inputSchema") or tool.get("parameters") or {}
                        plugin_loader.tools.append(PluginTool(
                            name=wrapped,
                            description=tool.get("description", ""),
                            parameters=params.get("properties", {}),
                            handler=self._make_handler(name, raw_name),
                        ))
                logger.info("MCP server '{}' connected with {} tools", name, len(client.tools))
            except Exception as exc:
                logger.error("Failed to connect MCP server '{}': {}", name, exc)

    async def stop(self) -> None:
        await self.pool.disconnect_all()

    def _make_handler(self, pool_name: str, tool_name: str) -> Any:
        async def handler(**params: Any) -> str:
            client = self.pool.get_client(pool_name)
            if not client:
                return f"[error] MCP server '{pool_name}' not connected"
            try:
                result = await client.call_tool(tool_name, params)
                if result and isinstance(result, list) and isinstance(result[0], dict):
                    text = result[0].get("text")
                    if text is not None:
                        return str(text)
                return str(result)
            except Exception as exc:
                logger.error("MCP tool {}.{} failed: {}", pool_name, tool_name, exc)
                return f"[error] MCP tool call failed: {exc}"
        return handler

    @property
    def connected_count(self) -> int:
        return self.pool.connected_count

    def list_servers_info(self) -> list[dict[str, Any]]:
        infos: list[dict[str, Any]] = []
        for name in list(self.pool._clients.keys()):
            client = self.pool.get_client(name)
            tools = len(client.tools) if client else 0
            infos.append({"name": name, "tools": tools})
        return infos
