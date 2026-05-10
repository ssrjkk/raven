from __future__ import annotations
import json
import httpx
from loguru import logger

PLUGIN_NAME = "api"
PLUGIN_DESCRIPTION = "Make HTTP requests to external APIs (GET, POST, PUT, DELETE)"


async def http_get(url: str, headers: str = "{}", timeout: int = 30) -> str:
    """Make an HTTP GET request. Args: url (str): Request URL, headers (str): JSON dict of headers, timeout (int): Timeout in seconds"""
    try:
        h = json.loads(headers) if isinstance(headers, str) else headers
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=h)
        return _format_response(resp)
    except Exception as e:
        return f"HTTP GET error: {e}"


async def http_post(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    """Make an HTTP POST request with JSON body. Args: url (str): Request URL, data (str): JSON body, headers (str): JSON headers, timeout (int): Timeout"""
    try:
        h = json.loads(headers) if isinstance(headers, str) else headers
        body = json.loads(data) if isinstance(data, str) else data
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(url, json=body, headers=h)
        return _format_response(resp)
    except Exception as e:
        return f"HTTP POST error: {e}"


async def http_put(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    """Make an HTTP PUT request with JSON body. Args: url (str): Request URL, data (str): JSON body, headers (str): JSON headers, timeout (int): Timeout"""
    try:
        h = json.loads(headers) if isinstance(headers, str) else headers
        body = json.loads(data) if isinstance(data, str) else data
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.put(url, json=body, headers=h)
        return _format_response(resp)
    except Exception as e:
        return f"HTTP PUT error: {e}"


async def http_delete(url: str, headers: str = "{}", timeout: int = 30) -> str:
    """Make an HTTP DELETE request. Args: url (str): Request URL, headers (str): JSON headers, timeout (int): Timeout"""
    try:
        h = json.loads(headers) if isinstance(headers, str) else headers
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.delete(url, headers=h)
        return _format_response(resp)
    except Exception as e:
        return f"HTTP DELETE error: {e}"


def _format_response(resp: httpx.Response) -> str:
    content_type = resp.headers.get("content-type", "")
    text = resp.text[:4000]
    if "application/json" in content_type:
        try:
            parsed = resp.json()
            text = json.dumps(parsed, indent=2, ensure_ascii=False)[:4000]
        except Exception:
            pass
    return f"[{resp.status_code}] {resp.reason_phrase}\n{text}"
