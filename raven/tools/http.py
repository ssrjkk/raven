from __future__ import annotations

from typing import Any

import httpx

from raven.core.security.ssrf import SSRFSafeTransport, validate_url
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_MAX_BODY_CHARS = 20_000
_MAX_REDIRECTS = 5


async def _read_limited_text(resp: Any) -> str:
    if hasattr(resp, "aiter_text"):
        chunks: list[str] = []
        total = 0
        async for chunk in resp.aiter_text():
            need = _MAX_BODY_CHARS + 1 - total
            if need <= 0:
                break
            chunks.append(chunk[:need])
            total += len(chunks[-1])
            if total > _MAX_BODY_CHARS:
                break
        return "".join(chunks)[:_MAX_BODY_CHARS]
    text = resp.text
    assert isinstance(text, str)
    return text[:_MAX_BODY_CHARS]


async def _fetch(url: str, method: str = "GET", **kwargs: Any) -> str:
    blocked = validate_url(url)
    if blocked:
        return f"[blocked] {blocked}"
    transport = SSRFSafeTransport()
    async with httpx.AsyncClient(transport=transport, timeout=30, follow_redirects=False) as c:
        try:
            resp = await c.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
            return f"[blocked] {e}"
        for _ in range(_MAX_REDIRECTS):
            if resp.is_redirect or resp.is_informational:
                location = resp.headers.get("Location")
                if not location:
                    break
                blocked = validate_url(location)
                if blocked:
                    return f"[blocked] redirect blocked: {blocked}"
                redirect_method = method
                redirect_kwargs = dict(kwargs)
                if resp.status_code in (301, 302) and method == "POST":
                    redirect_method = "GET"
                    redirect_kwargs.pop("content", None)
                try:
                    resp = await c.request(redirect_method, location, **redirect_kwargs)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as e:
                    return f"[blocked] redirect blocked: {e}"
            else:
                break
        if resp.is_redirect:
            return "[blocked] too many redirects"
        return await _read_limited_text(resp)


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
