from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from raven.core.mcp.auth import authorize_request
from raven.core.mcp.server import MCPServer
from raven.core.mcp.sse_transport import SSETransport
from raven.core.security.tool_policy import mcp_deny_reason
from ravencode.runtime.tools import execute_tool_public, get_mcp_tool_definitions

_mcp_server = MCPServer()
_sse_transport = SSETransport()


def create_mcp_router() -> APIRouter:
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.post("/rpc")
    async def mcp_rpc(request: Request) -> JSONResponse:
        if not await authorize_request(request):
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Unauthorized"}}, status_code=401
            )
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
    async def list_tools(request: Request) -> JSONResponse:
        if not await authorize_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        defs = get_mcp_tool_definitions()
        return JSONResponse(
            [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"],
                    "annotations": tool["annotations"],
                }
                for tool in defs
            ]
        )

    @router.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> JSONResponse:
        if not await authorize_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body: Any = await request.json() or {}
        args = body.get("arguments", body) if isinstance(body, dict) else {}
        denial = await mcp_deny_reason(name, args)
        if denial:
            return JSONResponse({"error": denial, "denied": True}, status_code=403)
        result = await execute_tool_public(name, args)
        return JSONResponse({"result": result})

    @router.get("/events")
    async def mcp_events(request: Request) -> StreamingResponse:
        client_id = f"mcp_{id(request)}"
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
        return {"status": "ok", "server": "raven-mcp"}

    return router
