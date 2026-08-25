from __future__ import annotations

import json

import pytest

from raven.tools.nodes import NodeManager, _node_manager, nodes_exec, nodes_list, nodes_register, nodes_unregister


@pytest.fixture(autouse=True)
def reset_nodes():
    _node_manager._nodes.clear()
    yield


class TestNodeManager:
    async def test_register_and_list(self):
        await _node_manager.register("test-node", "http://localhost:9999", ["shell"])
        nodes = await _node_manager.list_nodes()
        names = [n["name"] for n in nodes]
        assert "test-node" in names

    async def test_unregister(self):
        nid = await _node_manager.register("test-node", "http://localhost:9999", [])
        ok = await _node_manager.unregister(nid)
        assert ok is True

    async def test_broadcast_empty(self):
        results = await _node_manager.broadcast("echo hi", {})
        assert results == []

    async def test_register_rejects_non_http_scheme(self):
        result = await _node_manager.register("bad", "ftp://example.com", [])
        assert result.startswith("[blocked]")

    async def test_register_rejects_missing_hostname(self):
        result = await _node_manager.register("bad", "not-a-url", [])
        assert result.startswith("[blocked]")

    async def test_execute_unknown_node(self):
        result = await _node_manager.execute("nope", "ping", {})
        assert "[error] node not found" in result

    async def test_execute_blocked_endpoint_tampering(self):
        nid = await _node_manager.register("n", "http://localhost:9999", [])
        _node_manager._nodes[nid].endpoint = "file:///etc/passwd"
        result = await _node_manager.execute(nid, "ping", {})
        assert result.startswith("[blocked]")

    async def test_execute_success(self, monkeypatch: pytest.MonkeyPatch):
        import httpx

        nid = await _node_manager.register("n", "http://localhost:9999", [])

        class _Resp:
            text = "pong"

            def raise_for_status(self) -> None:
                return None

        class _Client:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, url: str, json: dict[str, object]) -> _Resp:
                return _Resp()

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        result = await _node_manager.execute(nid, "ping", {"x": 1})
        assert result == "pong"

    async def test_execute_http_error(self, monkeypatch: pytest.MonkeyPatch):
        import httpx

        nid = await _node_manager.register("n", "http://localhost:9999", [])

        class _Resp:
            text = ""

            def raise_for_status(self) -> None:
                raise httpx.HTTPStatusError("500", request=None, response=None)  # type: ignore[arg-type]

        class _Client:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, url: str, json: dict[str, object]) -> _Resp:
                return _Resp()

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        result = await _node_manager.execute(nid, "ping", {})
        assert result.startswith("[error]")

    async def test_broadcast_only_online(self, monkeypatch: pytest.MonkeyPatch):
        import httpx

        await _node_manager.register("up", "http://localhost:1", [])
        down_id = await _node_manager.register("down", "http://localhost:2", [])
        _node_manager._nodes[down_id].status = "offline"

        calls: list[str] = []

        class _Resp:
            text = "ok"

            def raise_for_status(self) -> None:
                return None

        class _Client:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, url: str, json: dict[str, object]) -> _Resp:
                calls.append(url)
                return _Resp()

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        results = await _node_manager.broadcast("ping", {})
        assert len(results) == 1
        assert "[up]" in results[0]


class TestNodesTools:
    async def test_list_empty(self):
        result = await nodes_list()
        assert "(no nodes registered)" in result

    async def test_exec_invalid_json(self):
        result = await nodes_exec("any", "ping", "{not json")
        assert "[error] invalid JSON payload" in result

    async def test_register_tool_wrapper(self):
        result = await nodes_register("wrapped", "http://localhost:9999", "shell, exec")
        assert "registered with id" in result
        nodes = await _node_manager.list_nodes()
        caps = next(n["capabilities"] for n in nodes if n["name"] == "wrapped")
        assert caps == ["shell", "exec"]
        assert json.dumps(caps)  # capabilities are JSON-serializable strings

    async def test_unregister_tool_wrapper_not_found(self):
        result = await nodes_unregister("ghost")
        assert "not found" in result
