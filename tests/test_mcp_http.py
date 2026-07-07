from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from ravencode.mcp.http_transport import create_mcp_router


@pytest.fixture
def router():
    return create_mcp_router()


@pytest.mark.asyncio
async def test_health_endpoint(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_list_tools(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
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
async def test_rpc_initialize(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp/rpc", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert "serverInfo" in data.get("result", {})


@pytest.mark.asyncio
async def test_rpc_tools_list(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp/rpc", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data.get("result", {})


@pytest.mark.asyncio
async def test_rpc_method_not_found(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp/rpc", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "nonexistent",
            "params": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


@pytest.mark.asyncio
async def test_rpc_invalid_body(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp/rpc", content="not json", headers={"Content-Type": "application/json"})
        assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_call_tool_direct(router):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp/tools/think", json={"arguments": {"reasoning": "test"}})
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
