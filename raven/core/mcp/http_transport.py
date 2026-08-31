from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from raven.core.auth.tokens import token_manager
from raven.core.config import get_settings
from raven.core.mcp.server import MCPServer
from raven.core.mcp.sse_transport import SSETransport
from ravencode.runtime.tools import execute_tool, get_tool_definitions

_mcp_server = MCPServer()
_sse_transport = SSETransport()


def _authorized(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    token = request.headers.get("X-Raven-Key", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        return False
    if token_manager.validate_token(token):
        return True
    key = get_settings().web_secret_key.get_secret_value()
    return bool(key) and hmac.compare_digest(token, key)


def create_mcp_router() -> APIRouter:
    router = APIRouter(prefix="/mcp", tags=["mcp"])

    @router.post("/rpc")
    async def mcp_rpc(request: Request) -> JSONResponse:
        if not _authorized(request):
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
        return JSONResponse(result)

    @router.get("/tools")
    async def list_tools(request: Request) -> JSONResponse:
        if not _authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
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
        return JSONResponse(result)

    @router.post("/tools/{name}")
    async def call_tool(name: str, request: Request) -> JSONResponse:
        if not _authorized(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        body: Any = await request.json() or {}
        args = body.get("arguments", body) if isinstance(body, dict) else {}
        result = await execute_tool(name, args)
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
