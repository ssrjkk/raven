from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

PRIVATE_NETS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in PRIVATE_NETS)
    except ValueError:
        return False


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        addrs = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        seen: set[Any] = set()
        result: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for _, _, _, _, sa in addrs:
            ip_str = sa[0]
            if ip_str not in seen:
                seen.add(ip_str)
                try:
                    result.append(ipaddress.ip_address(ip_str))
                except ValueError:
                    continue
        return result
    except Exception as exc:
        from loguru import logger
        logger.debug("SSRF DNS resolution failed for {}: {}", host, exc)
        return []


async def _resolve_host_async(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    loop = asyncio.get_running_loop()
    try:
        addrs = await loop.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        seen: set[str] = set()
        result: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for _, _, _, _, sa in addrs:
            ip_str = sa[0]
            if ip_str not in seen:
                seen.add(ip_str)
                try:
                    result.append(ipaddress.ip_address(ip_str))
                except ValueError:
                    continue
        return result
    except Exception as exc:
        from loguru import logger
        logger.debug("SSRF async DNS resolution failed for {}: {}", host, exc)
        return []


def is_private_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if host in ("localhost", "localhost.localdomain", "127.0.0.1", "::1", "0.0.0.0"):  # noqa: S104
        return True
    try:
        ips = _resolve_host(host)
        for ip in ips:
            if any(ip in net for net in PRIVATE_NETS):
                return True
    except Exception as exc:
        from loguru import logger
        logger.debug("SSRF IP resolution error for {}: {}", host, exc)
    try:
        ip = ipaddress.ip_address(host)
        if any(ip in net for net in PRIVATE_NETS):
            return True
    except ValueError:
        from loguru import logger
        logger.debug("SSRF host '{}' is not an IP and DNS resolution failed", host)
    return host.endswith(".local") or host.endswith(".internal")


def validate_url(url: str) -> str | None:
    from raven.core.config import get_settings

    if get_settings().ghost_mode:
        if not is_private_url(url):
            return f"Ghost mode: external URL blocked: {url[:100]}"
        return None
    if is_private_url(url):
        return f"URL resolves to a private IP range: {url[:100]}"
    return None


async def validate_url_async(url: str) -> str | None:
    """Асинхронная версия validate_url с DNS resolution."""
    from raven.core.config import get_settings

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Invalid scheme: {parsed.scheme}"
    host = parsed.hostname or ""
    if not host:
        return "Missing hostname"

    # Проверка, не IP ли это
    try:
        ipaddress.ip_address(host)
        if _is_private_ip(host):
            return f"Direct request to private IP: {host}"
        return None
    except ValueError:
        pass

    if get_settings().ghost_mode:
        return f"Ghost mode: external URL blocked: {url[:100]}"

    # Резолвим hostname асинхронно
    ips = await _resolve_host_async(host)
    if not ips:
        return f"Failed to resolve hostname: {host}"

    for ip in ips:
        if any(ip in net for net in PRIVATE_NETS):
            return f"Hostname resolves to private IP: {ip}"

    return None


class SSRFSafeTransport(httpx.AsyncHTTPTransport):
    """Custom HTTP transport с DNS pinning для защиты от DNS rebinding.

    1. Резолвит hostname один раз перед подключением
    2. Проверяет resolved IP на приватность
    3. Подключается к resolved IP (Host header остаётся оригинальным)
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host

        # Проверка, не IP ли это
        try:
            ipaddress.ip_address(hostname)
            if _is_private_ip(hostname):
                raise httpx.ConnectError(f"Request to private IP blocked: {hostname}")
            return await super().handle_async_request(request)
        except ValueError:
            pass

        # Это hostname — резолвим асинхронно
        ips = await _resolve_host_async(hostname)
        if not ips:
            raise httpx.ConnectError(f"Failed to resolve hostname: {hostname}")

        for ip in ips:
            if _is_private_ip(str(ip)):
                raise httpx.ConnectError(f"SSRF protection: hostname {hostname} resolves to private IP: {ip}")

        # DNS pinning: подставляем первый публичный IP вместо hostname
        pinned = str(ips[0])
        request.url = request.url.copy_with(host=pinned)

        return await super().handle_async_request(request)


async def safe_http_request(url: str, **kwargs: Any) -> httpx.Response:
    transport = SSRFSafeTransport()
    async with httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=30.0) as client:
        response = await client.request(url=url, **kwargs)
        if response.is_redirect:
            location = response.headers.get("Location")
            if location:
                error = validate_url(location)
                if error:
                    raise httpx.ConnectError(f"Redirect blocked by SSRF: {error}")
        return response
