from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from raven.core.mcp.server import MCPServer
from ravencode.runtime.tools import execute_tool, get_tool_definitions

_mcp_server = MCPServer()


def create_mcp_router() -> APIRouter:
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.post("/rpc")
    async def mcp_rpc(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}}, status_code=400)
        result = await _mcp_server.handle_request(body)
        return JSONResponse(result)

    @router.get("/tools")
    async def list_tools() -> list[dict[str, Any]]:
        defs = get_tool_definitions()
        result = []
        for d in defs:
            fn = d.get("function", d)
            if isinstance(fn, dict):
                result.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                })
        return result

    @router.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> JSONResponse:
        body: Any = await request.json() or {}
        args = body.get("arguments", body) if isinstance(body, dict) else {}
        result = await execute_tool(name, args)
        return JSONResponse({"result": result})

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "server": "raven-mcp"}

    return router
