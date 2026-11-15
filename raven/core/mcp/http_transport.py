from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from raven.core.mcp.auth import authorize_request
from raven.core.mcp.server import MCPServer
from raven.core.mcp.sse_transport import publish_tool_event, shared_transport
from raven.core.security.tool_policy import mcp_deny_reason
from ravencode.runtime.tools import execute_tool_public, get_mcp_tool_definitions

_mcp_server = MCPServer()
_sse_transport = shared_transport()


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
            await publish_tool_event(name, "denied")
            return JSONResponse({"error": denial, "denied": True}, status_code=403)
        result = await execute_tool_public(name, args)
        await publish_tool_event(name, "ok")
        return JSONResponse({"result": result})

    @router.get("/events")
    async def mcp_events(request: Request) -> Response:
        if not await authorize_request(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        # `id(request)` is only unique among live objects; two clients connected at once could be
        # handed the same key, and the second `subscribe()` would replace the first one's queue, so
        # one of them would stream the other's events and the loser would receive nothing.
        client_id = f"mcp_{uuid4().hex}"
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
