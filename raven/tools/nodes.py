from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


class NodeManager:
    def __init__(self) -> None:
        self._nodes: dict[str, NodeInfo] = {}
        self._lock = asyncio.Lock()

    async def register(self, name: str, endpoint: str, capabilities: list[str] | None = None) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return f"[blocked] node endpoint must be an http(s) URL: {endpoint[:100]}"
        nid = uuid.uuid4().hex[:8]
        async with self._lock:
            self._nodes[nid] = NodeInfo(
                id=nid,
                name=name,
                endpoint=endpoint,
                capabilities=capabilities or [],
                status="online",
                last_seen=datetime.now(UTC).isoformat(),
            )
        logger.info("Node registered: {} ({}) at {}", name, nid, endpoint)
        return nid

    async def unregister(self, nid: str) -> bool:
        async with self._lock:
            if nid not in self._nodes:
                return False
            del self._nodes[nid]
        logger.info("Node unregistered: {}", nid)
        return True

    async def list_nodes(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                {"id": n.id, "name": n.name, "endpoint": n.endpoint, "capabilities": n.capabilities, "status": n.status}
                for n in self._nodes.values()
            ]

    async def execute(self, nid: str, action: str, payload: dict[str, Any]) -> str:
        async with self._lock:
            node = self._nodes.get(nid)
        if not node:
            return f"[error] node not found: {nid}"
        try:
            from urllib.parse import urlparse

            import httpx

            parsed = urlparse(node.endpoint)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return f"[blocked] node endpoint must be an http(s) URL: {node.endpoint[:100]}"

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{node.endpoint}/exec",
                    json={"action": action, "payload": payload},
                )
                resp.raise_for_status()
                return resp.text[:5000]
        except Exception as exc:
            return f"[error] node execution failed: {exc}"

    async def broadcast(self, action: str, payload: dict[str, Any]) -> list[str]:
        results = []
        async with self._lock:
            nodes = list(self._nodes.values())
        for node in nodes:
            if node.status == "online":
                result = await self.execute(node.id, action, payload)
                results.append(f"[{node.name}] {result}")
        return results


@dataclass
class NodeInfo:
    id: str
    name: str
    endpoint: str
    capabilities: list[str] = field(default_factory=list)
    status: str = "online"
    last_seen: str = ""


_node_manager = NodeManager()


def get_node_manager() -> NodeManager:
    return _node_manager


async def nodes_list() -> str:
    nodes = await _node_manager.list_nodes()
    if not nodes:
        return "(no nodes registered)"
    return "\n".join(
        f"• {n['name']} ({n['id']}) — {n['endpoint']} [{n['status']}] — {', '.join(n['capabilities'])}" for n in nodes
    )


async def nodes_register(name: str, endpoint: str, capabilities: str = "") -> str:
    caps = [c.strip() for c in capabilities.split(",") if c.strip()]
    nid = await _node_manager.register(name, endpoint, caps)
    return f"Node '{name}' registered with id {nid}"


async def nodes_unregister(node_id: str) -> str:
    ok = await _node_manager.unregister(node_id)
    return f"Node {node_id} removed" if ok else f"Node {node_id} not found"


async def nodes_exec(node_id: str, action: str, payload_json: str = "{}") -> str:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return "[error] invalid JSON payload"
    return await _node_manager.execute(node_id, action, payload)


def register_nodes_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="nodes_list",
            description="List all registered execution nodes",
            parameters={},
            handler=nodes_list,
            category="system",
        )
    )
    registry.register(
        ToolSpec(
            name="nodes_register",
            description="Register a new execution node",
            parameters={
                "name": {"type": "string", "description": "Node name", "required": True},
                "endpoint": {"type": "string", "description": "Node API endpoint", "required": True},
                "capabilities": {"type": "string", "description": "Comma-separated capabilities", "required": False},
            },
            handler=nodes_register,
            category="system",
        )
    )
    registry.register(
        ToolSpec(
            name="nodes_unregister",
            description="Remove a registered node",
            parameters={"node_id": {"type": "string", "description": "Node ID", "required": True}},
            handler=nodes_unregister,
            category="system",
        )
    )
    registry.register(
        ToolSpec(
            name="nodes_exec",
            description="Execute an action on a remote node",
            parameters={
                "node_id": {"type": "string", "description": "Node ID", "required": True},
                "action": {"type": "string", "description": "Action to execute", "required": True},
                "payload_json": {"type": "string", "description": "JSON payload", "required": False},
            },
            handler=nodes_exec,
            category="system",
        )
    )
