"""MCP (Model Context Protocol) server for ravencode.

Delegates to the canonical implementation in ``raven.core.mcp.server``
and overrides the server identity.
"""

from __future__ import annotations

from raven.core.mcp.server import MCPServer as _BaseMCPServer


class MCPServer(_BaseMCPServer):
    server_name: str = "ravencode"


async def run_mcp_server() -> None:
    server = MCPServer()
    await server.run()
