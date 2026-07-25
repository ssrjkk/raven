from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.security.ssrf import validate_url


async def handle_capability(plugin_name: str, capability: str, args: dict[str, Any]) -> str | None:
    if capability == "safe_http":
        return await _cap_safe_http(plugin_name, args)
    if capability == "safe_file_read":
        return await _cap_safe_file_read(plugin_name, args)
    if capability == "safe_file_write":
        return await _cap_safe_file_write(plugin_name, args)
    logger.warning("[plugin] unknown capability requested by {}: {}", plugin_name, capability)
    return None


async def _cap_safe_http(plugin_name: str, args: dict[str, Any]) -> str:
    method = args.get("method", "GET")
    url = args.get("url", "")
    headers = args.get("headers", {})
    body = args.get("body")

    blocked = validate_url(url)
    if blocked:
        return f"[blocked] {blocked}"

    from raven.tools.http import _fetch

    kwargs: dict[str, Any] = {"headers": headers}
    if body:
        kwargs["content"] = body
    if method.upper() == "POST":
        return await _fetch(url, "POST", **kwargs)
    if method.upper() == "GET":
        return await _fetch(url, "GET", **kwargs)
    return f"[error] unsupported method: {method}"


async def _cap_safe_file_read(plugin_name: str, args: dict[str, Any]) -> str:
    from raven.tools.file import file_read

    return await file_read(args.get("path", ""), max_size=args.get("max_size", 50000))


async def _cap_safe_file_write(plugin_name: str, args: dict[str, Any]) -> str:
    from raven.tools.file import file_write

    return await file_write(args.get("path", ""), args.get("content", ""))
