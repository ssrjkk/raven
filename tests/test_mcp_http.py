from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from ravencode.mcp.http_transport import create_mcp_router


@pytest.fixture
def app():
    from fastapi import FastAPI

    application = FastAPI()
    application.include_router(create_mcp_router())
    return application


@pytest.fixture
def authed():
    with patch("ravencode.mcp.http_transport.authorize_request", return_value=True):
        yield


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/mcp/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_tools(client, authed):
    resp = await client.get("/mcp/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert isinstance(tools, list)
    assert len(tools) > 0
    names = [t["name"] for t in tools if t.get("name")]
    assert "read" in names, f"read not found in {names}"
    assert "write" in names
    assert "bash" in names


@pytest.mark.asyncio
async def test_rpc_initialize(client, authed):
    resp = await client.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert "serverInfo" in data.get("result", {})


@pytest.mark.asyncio
async def test_rpc_tools_list(client, authed):
    resp = await client.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert resp.status_code == 200
    assert "tools" in resp.json().get("result", {})


@pytest.mark.asyncio
async def test_rpc_method_not_found(client, authed):
    resp = await client.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}})
    assert resp.status_code == 200
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_rpc_invalid_body(client, authed):
    resp = await client.post("/mcp/rpc", content="not json", headers={"Content-Type": "application/json"})
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_call_tool_direct(client, authed):
    resp = await client.post("/mcp/tools/think", json={"arguments": {"reasoning": "test"}})
    assert resp.status_code == 200
    assert "result" in resp.json()


@pytest.mark.asyncio
async def test_tools_reject_anonymous(client):
    assert (await client.get("/mcp/tools")).status_code == 401
    assert (await client.post("/mcp/rpc", json={"method": "initialize"})).status_code == 401
    assert (await client.post("/mcp/tools/think", json={"arguments": {}})).status_code == 401
