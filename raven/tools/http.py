from __future__ import annotations

from typing import Any

import httpx

from raven.core.security.ssrf import validate_url
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def _fetch(url: str, method: str = "GET", **kwargs: Any) -> str:
    blocked = validate_url(url)
    if blocked:
        return f"[blocked] {blocked}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as c:
        resp = await c.request(method, url, **kwargs)
        for _ in range(5):
            if resp.is_redirect or resp.is_informational:
                location = resp.headers.get("Location")
                if not location:
                    break
                blocked = validate_url(location)
                if blocked:
                    return f"[blocked] redirect blocked: {blocked}"
                resp = await c.request(method, location, **kwargs)
            else:
                break
        if resp.is_redirect:
            return "[blocked] too many redirects"
        return resp.text[:20000]


async def http_get(url: str, headers: str | None = None) -> str:
    hdrs = {}
    if headers:
        for line in headers.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                hdrs[k.strip()] = v.strip()
    return await _fetch(url, headers=hdrs)


async def http_post(url: str, body: str = "", content_type: str = "application/json") -> str:
    return await _fetch(url, "POST", content=body, headers={"Content-Type": content_type})


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
