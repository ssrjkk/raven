from __future__ import annotations

from typing import Any

import httpx

from raven.core.monitor.models import Monitor


async def check_http(monitor: Monitor) -> dict[str, Any]:
    method = monitor.config.get("method", "GET").upper()
    headers = monitor.config.get("headers", {})
    body = monitor.config.get("body", "")
    follow = monitor.config.get("follow_redirects", True)
    timeout = monitor.config.get("timeout", 15)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow) as c:
        if method == "GET":
            resp = await c.get(monitor.target, headers=headers)
        elif method == "HEAD":
            resp = await c.head(monitor.target, headers=headers)
        elif method == "POST":
            resp = await c.post(monitor.target, headers=headers, content=body)
        else:
            resp = await c.request(method, monitor.target, headers=headers, content=body)

        content = resp.text[:5000]

        return {
            "status_code": resp.status_code,
            "response_time_ms": resp.elapsed.total_seconds() * 1000,
            "content_length": len(resp.content),
            "content_preview": content[:200],
            "content_contains": content,
        }
