from __future__ import annotations

import pytest

from raven.tools.nodes import NodeManager, _node_manager, nodes_list


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


class TestNodesTools:
    async def test_list_empty(self):
        result = await nodes_list()
        assert "(no nodes registered)" in result
