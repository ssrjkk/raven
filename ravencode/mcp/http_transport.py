"""HTTP transport for the MCP server.

Exposes ravencode MCP tools over HTTP POST (JSON-RPC) and SSE.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from raven.core.mcp.auth import authorize_request
from raven.core.mcp.sse_transport import SSETransport
from ravencode.mcp.server import MCPServer
from ravencode.runtime.tools import execute_tool_public, get_tool_definitions

_mcp_server = MCPServer()
_sse_transport = SSETransport()


def _require_auth(request: Request) -> None:
    if not authorize_request(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_mcp_router() -> APIRouter:
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.post("/rpc")
    async def mcp_rpc(request: Request) -> JSONResponse:
        _require_auth(request)
        try:
            body: Any = await request.json()
        except ValueError:
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status_code=400
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}}, status_code=400
            )
        result = await _mcp_server.handle_request(body)
        if result is None:
            return JSONResponse(None)
        return JSONResponse(result)

    @router.get("/tools")
    async def list_tools(request: Request) -> list[dict[str, Any]]:
        _require_auth(request)
        defs = get_tool_definitions()
        result = []
        for d in defs:
            fn = d.get("function", d)
            if isinstance(fn, dict):
                result.append(
                    {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                    }
                )
        return result

    @router.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> JSONResponse:
        _require_auth(request)
        body: Any = await request.json() or {}
        args = body.get("arguments", body) if isinstance(body, dict) else {}
        result = await execute_tool_public(name, args)
        return JSONResponse({"result": result})

    @router.get("/events")
    async def mcp_events(request: Request) -> StreamingResponse:
        client_id = f"ravencode_mcp_{id(request)}"
        _sse_transport.subscribe(client_id)
        async def _event_stream() -> Any:
            try:
                async for chunk in _sse_transport.stream(client_id):
                    yield chunk
            finally:
                _sse_transport.unsubscribe(client_id)
        return StreamingResponse(_event_stream(), media_type="text/event-stream")

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "server": "ravencode-mcp"}

    return router
