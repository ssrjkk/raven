from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.models import PluginTool
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


def _make_mcp_handler(pool_name: str, tool_name: str, mcp_pool: Any) -> Any:
    async def handler(**params: Any) -> str:
        logger.debug("Calling MCP tool {}.{} with {}", pool_name, tool_name, params)
        try:
            client = mcp_pool.get_client(pool_name)
            if not client:
                return f"[error] MCP server '{pool_name}' not connected"
            result = await client.call_tool(tool_name, params)
            return result[0]["text"] if result and isinstance(result, list) and "text" in result[0] else str(result)
        except Exception as exc:
            logger.error("MCP tool {}.{} failed: {}", pool_name, tool_name, exc)
            return f"[error] MCP tool call failed: {exc}"

    return handler


def register_mcp_tools(registry: ToolRegistry, mcp_pool: Any) -> None:
    if not hasattr(mcp_pool, "_clients"):
        return
    for name, client in mcp_pool._clients.items():
        for tool in client.tools:
            raw_name = tool.get("name", "unknown")
            tool_name = f"mcp_{name}_{raw_name}"
            params = tool.get("inputSchema") or tool.get("parameters") or {"type": "object", "properties": {}}
            registry.register(ToolSpec(
                name=tool_name,
                description=tool.get("description", ""),
                parameters=params.get("properties", {}),
                handler=_make_mcp_handler(name, raw_name, mcp_pool),
                category="mcp",
                timeout=60,
            ))


def create_mcp_plugin_tools(mcp_pool: Any) -> list[PluginTool]:
    tools: list[PluginTool] = []
    if not hasattr(mcp_pool, "_clients"):
        return tools
    for name, client in mcp_pool._clients.items():
        for tool in client.tools:
            raw_name = tool.get("name", "unknown")
            tool_name = f"mcp_{name}_{raw_name}"
            params = tool.get("inputSchema") or tool.get("parameters") or {"type": "object", "properties": {}}
            tools.append(PluginTool(
                name=tool_name,
                description=tool.get("description", ""),
                parameters=params.get("properties", {}),
                handler=_make_mcp_handler(name, raw_name, mcp_pool),
            ))
    return tools
