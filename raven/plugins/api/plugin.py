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

_client: httpx.AsyncClient | None = None


def _get_client(timeout: int = 30) -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        )
    return _client


def _is_private_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        for r in _PRIVATE_RANGES:
            if ip in ipaddress.ip_network(r, strict=False):
                return True
    except ValueError:
        pass
    return False


def _validate_url(url: str) -> tuple[str, ValueError | None]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return url, ValueError("URL missing hostname")
    if _is_private_ip(host):
        return url, ValueError(f"SSRF blocked: private IP {host}")
    if host in ("localhost", "0.0.0.0"):
        return url, ValueError(f"SSRF blocked: hostname {host}")
    try:
        addrs = socket.getaddrinfo(host, None)
        for _family, _, _, _, sockaddr in addrs:
            addr = str(sockaddr[0])
            if _is_private_ip(addr):
                return url, ValueError(f"SSRF blocked: {host} resolves to private IP {addr}")
    except (socket.gaierror, OSError) as e:
        logger.debug("[api] DNS resolution failed for {}: {}", host, e)
    return url, None


def _check_response_ssrf(resp: httpx.Response) -> str | None:
    if resp.has_redirect_location:
        redirect_url = str(resp.url)
        _, err = _validate_url(redirect_url)
        if err:
            return f"SSRF blocked on redirect: {err}"
    return None


async def _request(method: str, url: str, **kwargs) -> str:
    url, err = _validate_url(url)
    if err:
        return f"HTTP {method.upper()} blocked: {err}"
    try:
        h = kwargs.pop("headers", None)
        if h and isinstance(h, str):
            h = json.loads(h)
        if h:
            kwargs["headers"] = h
        client = _get_client()
        resp = await client.request(method, url, **kwargs)
        ssrf_err = _check_response_ssrf(resp)
        if ssrf_err:
            return ssrf_err
        if resp.is_redirect:
            final_url = str(resp.url)
            _, err = _validate_url(final_url)
            if err:
                return f"SSRF blocked on final URL: {err}"
        return _format_response(resp)
    except Exception as e:
        return f"HTTP {method.upper()} error: {e}"


async def http_get(url: str, headers: str = "{}", timeout: int = 30) -> str:
    return await _request("GET", url, headers=headers)


async def http_post(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    body = json.loads(data) if isinstance(data, str) else data
    return await _request("POST", url, json=body, headers=headers)


async def http_put(url: str, data: str = "{}", headers: str = "{}", timeout: int = 30) -> str:
    body = json.loads(data) if isinstance(data, str) else data
    return await _request("PUT", url, json=body, headers=headers)


async def http_delete(url: str, headers: str = "{}", timeout: int = 30) -> str:
    return await _request("DELETE", url, headers=headers, follow_redirects=False)


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
