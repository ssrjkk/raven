from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

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

_IP_FROM_HOST = re.compile(r"^https?://(\[[^\]]+\]|[^:/?#]+)")


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        from socket import getaddrinfo
        addrs = getaddrinfo(host, None, type=1)
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
    except Exception:
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
    except Exception:
        try:
            ip = ipaddress.ip_address(host)
            if any(ip in net for net in PRIVATE_NETS):
                return True
        except ValueError:
            pass
    return host.endswith(".local") or host.endswith(".internal")


def validate_url(url: str) -> str | None:
    if is_private_url(url):
        return f"URL resolves to a private IP range: {url[:100]}"
    return None
