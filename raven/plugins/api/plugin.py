from __future__ import annotations

import json

import httpx
from loguru import logger

from raven.core.security.ssrf import safe_fetch_async, validate_url

PLUGIN_NAME = "api"
PLUGIN_DESCRIPTION = "Make HTTP requests to external APIs (GET, POST, PUT, DELETE)"


async def _request(method: str, url: str, **kwargs) -> str:
    error = validate_url(url)
    if error:
        return f"HTTP {method.upper()} blocked: {error}"
    try:
        h = kwargs.pop("headers", None)
        if h and isinstance(h, str):
            try:
                h = json.loads(h)
                if not isinstance(h, dict):
                    return f"HTTP {method.upper()} error: headers must be a JSON object"
            except json.JSONDecodeError as e:
                return f"HTTP {method.upper()} error: invalid headers JSON: {e}"
        if h:
            kwargs["headers"] = h
        resp = await safe_fetch_async(url, method=method, **kwargs)
        return _format_response(resp)
    except ValueError as e:
        return f"HTTP {method.upper()} blocked: {e}"
    except Exception as e:
        return f"HTTP {method.upper()} error: {e}"


async def http_get(url: str, headers: str = "{}", timeout: int = 30) -> str:
    return await _request("GET", url, headers=headers, timeout=timeout)


async def http_post(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    body = _parse_body(data)
    if isinstance(body, str):
        return body
    return await _request("POST", url, json=body, headers=headers, timeout=timeout)


async def http_put(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    body = _parse_body(data)
    if isinstance(body, str):
        return body
    return await _request("PUT", url, json=body, headers=headers, timeout=timeout)


async def http_delete(url: str, headers: str = "{}", timeout: int = 30) -> str:
    return await _request("DELETE", url, headers=headers, timeout=timeout)


def _parse_body(data: str | object) -> object | str:
    if not isinstance(data, str):
        return data
    try:
        parsed: object = json.loads(data)
        return parsed
    except json.JSONDecodeError as e:
        return f"HTTP error: invalid JSON body: {e}"


def _format_response(resp: httpx.Response) -> str:
    content_type = resp.headers.get("content-type", "")
    text = resp.text[:4000]
    if "application/json" in content_type:
        try:
            parsed = resp.json()
            text = json.dumps(parsed, indent=2, ensure_ascii=False)[:4000]
        except Exception as e:
            logger.debug("Response JSON parse failed: {}", e)
    return f"[{resp.status_code}] {resp.reason_phrase}\n{text}"
