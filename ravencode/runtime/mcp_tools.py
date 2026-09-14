"""MCP tool integration for the ReAct agent.

Connects external MCP servers declared in the project config
(``mcp_servers`` in ravencode.json / opencode.json) and registers their
tools into the agent tool registry as ``mcp_{server}_{tool}``. Registered
tools are marked dangerous (they execute code outside the workspace) and
validate arguments against the server-provided JSON Schema.

Usage at an entry point that creates a ReActAgent::

    await ensure_mcp_tools()   # idempotent; logs and continues on failure
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger

from raven.core.mcp.mcp_client import MCPClient, get_mcp_pool
from ravencode.runtime.tools import MODULE_TOOLS, _build_tool_definitions

_tool_call_timeout = 120.0
_unsafe_chars = re.compile(r"[^a-zA-Z0-9_-]")
_registered_servers: set[str] = set()
_config_attempted = False


def _sanitize(part: str) -> str:
    return _unsafe_chars.sub("_", part)[:40] or "x"


def _format_content(content: Any) -> str:
    """Flatten MCP tool results (list of content blocks) into plain text."""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(f"[{block.get('type', 'unknown')} content]")
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else "(empty result)"
    return str(content)


def _make_handler(client: MCPClient, tool_name: str) -> Any:
    async def handler(**kwargs: Any) -> str:
        result = await asyncio.wait_for(
            client.call_tool(tool_name, dict(kwargs)), timeout=_tool_call_timeout
        )
        return _format_content(result)

    return handler


def register_client_tools(server: str, client: Any) -> list[str]:
    """Register a connected MCP client's tools into MODULE_TOOLS.

    ``client`` is any object exposing ``tools`` (MCP tool descriptors) and
    ``call_tool(name, arguments)`` — i.e. MCPClient or a test double.
    """
    prefix = f"mcp_{_sanitize(server)}_"
    registered: list[str] = []
    for tool in client.tools:
        raw_name = str(tool.get("name", "")).strip()
        if not raw_name:
            continue
        name = prefix + _sanitize(raw_name)
        if name in MODULE_TOOLS:
            continue
        schema = (
            tool.get("inputSchema")
            or tool.get("parameters")
            or {"type": "object", "properties": {}}
        )
        MODULE_TOOLS[name] = {
            "name": name,
            "dangerous": True,
            "description": f"[MCP:{server}] {tool.get('description', '')}".strip(),
            "parameters": schema,
            "handler": _make_handler(client, raw_name),
        }
        registered.append(name)
    if registered:
        _build_tool_definitions.cache_clear()
    return registered


async def connect_mcp_servers(servers: list[Any]) -> int:
    """Connect to every enabled MCP server spec; returns registered tool count.

    Failures are logged and skipped: one broken server must not block startup.
    """
    pool = get_mcp_pool()
    total = 0
    for spec in servers:
        if not isinstance(spec, dict) or spec.get("disabled"):
            continue
        name = str(spec.get("name") or "").strip()
        command = spec.get("command")
        if not name or not command:
            continue
        if name in _registered_servers or pool.get_client(name) is not None:
            continue
        cmd = [str(command)] + [str(a) for a in (spec.get("args") or [])]
        try:
            client = await pool.connect(name, cmd, cwd=spec.get("cwd"))
            registered = register_client_tools(name, client)
            _registered_servers.add(name)
            total += len(registered)
            logger.info("MCP '{}': registered {} tools", name, len(registered))
        except Exception as exc:
            logger.warning("MCP server '{}' failed to connect: {}", name, exc)
    return total


async def ensure_mcp_tools(servers: list[dict[str, Any]] | None = None) -> int:
    """Connect MCP servers from the given specs or the project config.

    Idempotent: already-connected servers are skipped. Safe to call before
    every agent creation.
    """
    global _config_attempted
    if servers is None:
        if _config_attempted:
            return 0
        _config_attempted = True
        try:
            from ravencode.config.loader import ConfigLoader

            servers = ConfigLoader().load_all().mcp_servers
        except Exception as exc:
            logger.debug("MCP config unavailable: {}", exc)
            return 0
    return await connect_mcp_servers(list(servers))


async def disconnect_mcp_servers() -> None:
    """Tear down all MCP connections (used on shutdown / in tests)."""
    _registered_servers.clear()
    global _config_attempted
    _config_attempted = False
    await get_mcp_pool().disconnect_all()
