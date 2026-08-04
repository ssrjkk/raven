from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from raven.core.http_client import client_manager
from raven.core.security.ssrf import validate_url_async

if TYPE_CHECKING:
    from raven.core.monitor.models import Monitor


async def check_http(monitor: Monitor) -> str | None:
    url = monitor.config.get("target", monitor.target)
    error = await validate_url_async(url)
    if error:
        return f"HTTP check blocked: {error}"
    method = monitor.config.get("method", "GET").upper()
    headers = monitor.config.get("headers", {})
    timeout = monitor.config.get("timeout", 15)
    body = monitor.config.get("body")
    content_match = monitor.config.get("content_match")

    try:
        if method == "GET":
            resp = await client_manager.request("GET", url, headers=headers, timeout=timeout)
        else:
            resp = await client_manager.request("POST", url, json=body, headers=headers, timeout=timeout)
    except Exception as exc:
        logger.error("HTTP check failed for {}: {}", url, exc)
        return f"HTTP check failed for {url}: {exc}"

    status = resp.status_code
    if status >= 400:
        return f"🔴 HTTP {status} for {url}"

    if content_match:
        text = resp.text or ""
        if content_match not in text:
            return f"🔴 Content check failed for {url}: expected '{content_match}' not found"

    return None
