from __future__ import annotations

import httpx

from raven.core.security.ssrf import validate_url
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def http_get(url: str, headers: str | None = None) -> str:
    blocked = validate_url(url)
    if blocked:
        return f"[blocked] {blocked}"
    hdrs = {}
    if headers:
        for line in headers.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                hdrs[k.strip()] = v.strip()
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.get(url, headers=hdrs)
        return resp.text[:20000]


async def http_post(url: str, body: str = "", content_type: str = "application/json") -> str:
    blocked = validate_url(url)
    if blocked:
        return f"[blocked] {blocked}"
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(url, content=body, headers={"Content-Type": content_type})
        return resp.text[:20000]


def register_http_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="http_get",
            description="Fetch a URL and return its content",
            parameters={
                "url": {"type": "string", "description": "URL to fetch", "required": True},
                "headers": {
                    "type": "string",
                    "description": "Optional headers, one per line (Key: Value)",
                    "required": False,
                },
            },
            handler=http_get,
            category="web",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="http_post",
            description="POST data to a URL",
            parameters={
                "url": {"type": "string", "description": "Target URL", "required": True},
                "body": {"type": "string", "description": "Request body", "required": False},
                "content_type": {"type": "string", "description": "Content-Type header", "required": False},
            },
            handler=http_post,
            category="web",
            timeout=30,
        )
    )
