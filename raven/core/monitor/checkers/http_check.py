from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.http_client import client_manager

if TYPE_CHECKING:
    from raven.core.monitor.models import Monitor


async def check_http(monitor: Monitor) -> str | None:
    url = monitor.config.get("target", monitor.target)
    method = monitor.config.get("method", "GET").upper()
    headers = monitor.config.get("headers", {})
    timeout = monitor.config.get("timeout", 15)
    body = monitor.config.get("body")
    content_match = monitor.config.get("content_match")

    try:
        if method == "GET":
            resp = await client_manager.get(url, headers=headers, timeout=timeout)
        else:
            resp = await client_manager.post(url, json=body, headers=headers, timeout=timeout)
    except Exception as exc:
        return f"🔴 HTTP check failed for {url}: {exc}"

    status = resp.status_code if hasattr(resp, "status_code") else 200
    if status >= 400:
        return f"🔴 HTTP {status} for {url}"

    if content_match:
        text = resp if isinstance(resp, str) else (resp.text if hasattr(resp, "text") else str(resp))
        if content_match not in text:
            return f"🔴 Content check failed for {url}: expected '{content_match}' not found"

    return None
