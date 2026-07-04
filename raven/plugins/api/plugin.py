from __future__ import annotations

import ipaddress
import json
import socket
from urllib.parse import urlparse

import httpx
from loguru import logger

PLUGIN_NAME = "api"
PLUGIN_DESCRIPTION = "Make HTTP requests to external APIs (GET, POST, PUT, DELETE)"

_PRIVATE_RANGES = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
]


def _validate_url(url: str) -> tuple[str, ValueError | None]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return url, ValueError("URL missing hostname")
    try:
        ip = ipaddress.ip_address(host)
        for r in _PRIVATE_RANGES:
            if ip in ipaddress.ip_network(r, strict=False):
                return url, ValueError(f"SSRF blocked: private IP {host}")
    except ValueError:
        if host in ("localhost", "0.0.0.0"):
            return url, ValueError(f"SSRF blocked: hostname {host}")
        try:
            addrs = socket.getaddrinfo(host, None)
            for _family, _, _, _, sockaddr in addrs:
                addr = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(addr)
                    for r in _PRIVATE_RANGES:
                        if ip in ipaddress.ip_network(r, strict=False):
                            return url, ValueError(f"SSRF blocked: {host} resolves to private IP {addr}")
                except ValueError:
                    continue
        except (socket.gaierror, OSError) as e:
            logger.debug("[api] DNS resolution failed for {}: {}", host, e)
    return url, None


async def http_get(url: str, headers: str = "{}", timeout: int = 30) -> str:
    """Make an HTTP GET request. Args: url (str): Request URL, headers (str): JSON dict of headers, timeout (int): Timeout in seconds"""
    url, err = _validate_url(url)
    if err:
        return f"HTTP GET blocked: {err}"
    try:
        h = json.loads(headers) if isinstance(headers, str) else headers
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=h)
        return _format_response(resp)
    except Exception as e:
        return f"HTTP GET error: {e}"


async def http_post(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    """Make an HTTP POST request with JSON body. Args: url (str): Request URL, data (str): JSON body, headers (str): JSON headers, timeout (int): Timeout"""
    url, err = _validate_url(url)
    if err:
        return f"HTTP POST blocked: {err}"
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
    url, err = _validate_url(url)
    if err:
        return f"HTTP PUT blocked: {err}"
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
    url, err = _validate_url(url)
    if err:
        return f"HTTP DELETE blocked: {err}"
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
        except Exception as e:
            logger.debug("Response JSON parse failed: {}", e)
    return f"[{resp.status_code}] {resp.reason_phrase}\n{text}"
