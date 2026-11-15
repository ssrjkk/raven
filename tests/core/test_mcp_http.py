from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from raven.core.mcp.http_transport import create_mcp_router
from raven.core.mcp.sse_transport import shared_transport


def _auth_req(**overrides: object) -> MagicMock:
    req = MagicMock(spec=Request)
    req.headers = {"Authorization": "Bearer test-token"}
    for key, val in overrides.items():
        setattr(req, key, val)
    return req


@pytest.fixture
def authed():
    with patch("raven.core.mcp.auth.token_manager") as tm:
        tm.validate_token = AsyncMock(return_value={"user_id": "u1", "role": "admin"})
        yield tm


class TestMCPHttp:
    @pytest.fixture
    def router(self):
        return create_mcp_router()

    def test_router_routes(self, router) -> None:
        routes = {r.path for r in router.routes}
        assert "/mcp/rpc" in routes
        assert "/mcp/tools" in routes
        assert "/mcp/tools/{name}" in routes
        assert "/mcp/events" in routes
        assert "/mcp/health" in routes

    async def test_health_endpoint(self, router, authed) -> None:
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/health" and "GET" in route.methods:
                resp = await route.endpoint()
                assert resp["status"] == "ok"
                return

    async def test_tools_endpoint(self, router, authed) -> None:
        defs = [
            {
                "name": "read_file",
                "description": "Read a file",
                "inputSchema": {},
                "annotations": {"destructiveHint": False, "openWorldHint": False},
            }
        ]
        with patch("raven.core.mcp.http_transport.get_mcp_tool_definitions", return_value=defs):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                    resp = await route.endpoint(request=_auth_req())
                    body = json.loads(resp.body)
                    assert len(body) == 1
                    assert body[0]["name"] == "read_file"
                    return

    async def test_tools_endpoint_no_function_wrapper(self, router, authed) -> None:
        defs = [
            {
                "name": "write_file",
                "description": "Write a file",
                "inputSchema": {},
                "annotations": {"destructiveHint": True, "openWorldHint": False},
            }
        ]
        with patch("raven.core.mcp.http_transport.get_mcp_tool_definitions", return_value=defs):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                    resp = await route.endpoint(request=_auth_req())
                    body = json.loads(resp.body)
                    assert len(body) == 1
                    assert body[0]["name"] == "write_file"
                    assert body[0]["annotations"] == {"destructiveHint": True, "openWorldHint": False}
                    assert body[0]["parameters"] == {}
                    return

    async def test_rpc_valid(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}}))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert body["result"]["serverInfo"]["name"] == "raven-mcp"
                return

    async def test_rpc_unauthorized(self, router) -> None:
        req = _auth_req(json=AsyncMock(return_value={"method": "initialize", "id": 1, "params": {}}))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                assert resp.status_code == 401
                return

    async def test_rpc_parse_error(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(side_effect=ValueError("bad json")))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert resp.status_code == 400
                assert body["error"]["code"] == -32700
                return

    async def test_rpc_invalid_type(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value="not a dict"))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/rpc" and "POST" in route.methods:
                resp = await route.endpoint(request=req)
                body = json.loads(resp.body)
                assert resp.status_code == 400
                assert body["error"]["code"] == -32600
                return

    async def test_call_tool(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value={"arguments": {"x": 1}}))
        with patch("raven.core.mcp.http_transport.execute_tool_public", new=AsyncMock(return_value="done")):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                    resp = await route.endpoint(name="echo", request=req)
                    body = json.loads(resp.body)
                    assert body["result"] == "done"
                    return

    async def test_call_tool_default_args(self, router, authed) -> None:
        req = _auth_req(json=AsyncMock(return_value={}))
        with patch("raven.core.mcp.http_transport.execute_tool_public", new=AsyncMock(return_value="ok")):
            for route in router.routes:
                if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                    resp = await route.endpoint(name="ping", request=req)
                    assert json.loads(resp.body)["result"] == "ok"
                    return

    async def test_tools_requires_auth(self, router) -> None:
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/tools" and "GET" in route.methods:
                resp = await route.endpoint(request=_auth_req())
                assert resp.status_code == 401
                return

    async def test_call_tool_requires_auth(self, router) -> None:
        req = _auth_req(json=AsyncMock(return_value={}))
        for route in router.routes:
            if getattr(route, "path", "") == "/mcp/tools/{name}" and "POST" in route.methods:
                resp = await route.endpoint(name="ping", request=req)
                assert resp.status_code == 401
                return


def _route(router, path: str, method: str):
    """The endpoint for a path, or a failure that names it.

    The `for route in router.routes: …: return` shape this file used before asserts nothing when the
    route is absent, so a deleted endpoint kept its test green; this one cannot.
    """
    for route in router.routes:
        if getattr(route, "path", "") == path and method in route.methods:
            return route.endpoint
    pytest.fail(f"the mcp router has no {method} {path}")


async def _wait_until(predicate: Callable[[], bool], *, attempts: int = 200) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    pytest.fail("the /mcp/events route never registered its subscriber")


def _payload(frame: str) -> dict[str, str]:
    """The JSON body of one SSE frame, and a frame that is really one."""
    assert frame.startswith("event: tool_call\ndata: "), repr(frame)
    assert frame.endswith("\n\n"), repr(frame)
    payload: dict[str, str] = json.loads(frame.split("data: ", 1)[1].strip())
    return payload


@pytest.fixture
def registry() -> Iterator[Any]:
    """The event registry is process-wide, so a subscriber or a stopped flag left here is billed to
    the next file in the run."""
    transport = shared_transport()
    before = dict(transport._subscribers)
    was_running = transport._running
    yield transport
    transport._subscribers.clear()
    transport._subscribers.update(before)
    transport._running = was_running


class TestMCPEventStream:
    """`GET /mcp/events` as the documented control: a caller that runs a tool sees it arrive.

    Everything here goes through the real transport. The version of these tests that patched
    `_sse_transport.stream` certified a control that could not work: the stream was gated on a
    `_running` flag only `start()` sets, and `start()` had zero call sites in the product, so the
    endpoint answered 200 and yielded no frame for any client, while the mocked test stayed green.
    """

    @pytest.fixture
    def router(self):
        return create_mcp_router()

    async def test_events_requires_a_credential(self, router) -> None:
        endpoint = _route(router, "/mcp/events", "GET")
        resp = await endpoint(request=_auth_req())
        assert resp.status_code == 401

    async def test_a_tool_call_over_http_reaches_the_stream(self, router, authed, registry) -> None:
        stream = _route(router, "/mcp/events", "GET")
        call = _route(router, "/mcp/tools/{name}", "POST")
        resp = await stream(request=_auth_req())
        frames = resp.body_iterator
        reading = asyncio.ensure_future(frames.__anext__())
        await _wait_until(lambda: len(registry._subscribers) > 0)
        req = _auth_req(json=AsyncMock(return_value={"arguments": {"path": "README.md"}}))
        with patch("raven.core.mcp.http_transport.execute_tool_public", new=AsyncMock(return_value="done")):
            assert json.loads((await call(name="read", request=req)).body)["result"] == "done"
        assert _payload(await asyncio.wait_for(reading, timeout=2)) == {"tool": "read", "status": "ok"}
        await frames.aclose()

    async def test_the_json_rpc_path_publishes_too(self, router, authed, registry) -> None:
        """The publisher lives in `server.py` and the reader in `http_transport.py`; two module-level
        `SSETransport()` instances made those halves invisible to each other."""
        stream = _route(router, "/mcp/events", "GET")
        rpc = _route(router, "/mcp/rpc", "POST")
        resp = await stream(request=_auth_req())
        frames = resp.body_iterator
        reading = asyncio.ensure_future(frames.__anext__())
        await _wait_until(lambda: len(registry._subscribers) > 0)
        req = _auth_req(json=AsyncMock(return_value={"method": "tools/call", "id": 7, "params": {"name": "read"}}))
        with patch("raven.core.mcp.server.execute_tool_public", new=AsyncMock(return_value="done")):
            await rpc(request=req)
        assert _payload(await asyncio.wait_for(reading, timeout=2)) == {"tool": "read", "status": "ok"}
        await frames.aclose()

    async def test_a_refused_call_is_on_the_stream(self, router, authed, registry) -> None:
        stream = _route(router, "/mcp/events", "GET")
        call = _route(router, "/mcp/tools/{name}", "POST")
        resp = await stream(request=_auth_req())
        frames = resp.body_iterator
        reading = asyncio.ensure_future(frames.__anext__())
        await _wait_until(lambda: len(registry._subscribers) > 0)
        req = _auth_req(json=AsyncMock(return_value={"arguments": {"cmd": "rm -rf /"}}))
        with patch("raven.core.mcp.http_transport.execute_tool_public", new=AsyncMock(return_value="nope")) as tool:
            assert (await call(name="shell", request=req)).status_code == 403
        assert _payload(await asyncio.wait_for(reading, timeout=2)) == {"tool": "shell", "status": "denied"}
        tool.assert_not_awaited()
        await frames.aclose()

    async def test_the_frame_carries_no_arguments_and_no_result(self, router, authed, registry) -> None:
        """One stream fans to every subscriber, so a frame that echoed what was read would show one
        observer another observer's file contents."""
        stream = _route(router, "/mcp/events", "GET")
        call = _route(router, "/mcp/tools/{name}", "POST")
        resp = await stream(request=_auth_req())
        frames = resp.body_iterator
        reading = asyncio.ensure_future(frames.__anext__())
        await _wait_until(lambda: len(registry._subscribers) > 0)
        req = _auth_req(json=AsyncMock(return_value={"arguments": {"path": "/secrets/argument-sentinel"}}))
        with patch("raven.core.mcp.http_transport.execute_tool_public", new=AsyncMock(return_value="result-sentinel")):
            await call(name="read", request=req)
        frame = await asyncio.wait_for(reading, timeout=2)
        assert "sentinel" not in frame, frame
        await frames.aclose()

    async def test_two_subscribers_do_not_share_one_queue(self, router, authed, registry) -> None:
        """Both calls are handed the same request object on purpose: `id(request)` is recycled once an
        object dies, so a key built from it can be the key a live client is already reading under."""
        stream = _route(router, "/mcp/events", "GET")
        req = _auth_req()
        first = (await stream(request=req)).body_iterator
        second = (await stream(request=req)).body_iterator
        reading_a = asyncio.ensure_future(first.__anext__())
        reading_b = asyncio.ensure_future(second.__anext__())
        await _wait_until(lambda: len(registry._subscribers) >= 2)
        await registry.send("tool_call", {"tool": "read", "status": "ok"})
        assert _payload(await asyncio.wait_for(reading_a, timeout=2)) == {"tool": "read", "status": "ok"}
        assert _payload(await asyncio.wait_for(reading_b, timeout=2)) == {"tool": "read", "status": "ok"}
        await first.aclose()
        await second.aclose()

    async def test_a_client_that_leaves_stops_counting(self, router, authed, registry) -> None:
        """The route's `finally` is the only thing that releases a subscriber, and it runs on the way out
        of the generator: a client that hangs up must not leave its queue registered to be fanned to."""
        stream = _route(router, "/mcp/events", "GET")
        call = _route(router, "/mcp/tools/{name}", "POST")
        before = len(registry._subscribers)
        resp = await stream(request=_auth_req())
        frames = resp.body_iterator
        reading = asyncio.ensure_future(frames.__anext__())
        await _wait_until(lambda: len(registry._subscribers) > before)
        req = _auth_req(json=AsyncMock(return_value={"arguments": {}}))
        with patch("raven.core.mcp.http_transport.execute_tool_public", new=AsyncMock(return_value="done")):
            await call(name="read", request=req)
        await asyncio.wait_for(reading, timeout=2)
        await frames.aclose()
        assert len(registry._subscribers) == before

    def test_both_http_modules_use_one_registry(self) -> None:
        import raven.core.mcp.http_transport as raven_http
        import ravencode.mcp.http_transport as ravencode_http

        assert raven_http._sse_transport is ravencode_http._sse_transport is shared_transport()
