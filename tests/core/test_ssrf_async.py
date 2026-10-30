from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from raven.core.security import ssrf
from raven.core.security.ssrf import (
    SSRFSafeTransport,
    _is_private_address,
    _is_private_ip,
    _materialize,
    _resolve_host,
    _resolve_host_async,
    is_private_url,
    safe_fetch_async,
    safe_http_request,
    validate_url,
    validate_url_async,
)


def _settings(monkeypatch: pytest.MonkeyPatch, *, ghost: bool) -> None:
    monkeypatch.setattr(ssrf, "get_settings", lambda: type("s", (), {"ghost_mode": ghost})())


def _ga(ips: list[str]) -> list[Any]:
    return [(None, None, None, None, (ip, 0)) for ip in ips]


# ── _is_private_address / _is_private_ip ──────────────────────────


def test_is_private_address_ipv6_mapped_recursion() -> None:
    assert _is_private_address(ipaddress.ip_address("::ffff:10.0.0.1")) is True


def test_is_private_address_public_ipv6() -> None:
    assert _is_private_address(ipaddress.ip_address("2606::1")) is False


def test_is_private_ip_invalid_string() -> None:
    assert _is_private_ip("not-an-ip") is False


# ── _resolve_host (sync) ──────────────────────────────────────────


def test_resolve_host_success_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ga(["1.1.1.1", "1.1.1.1", "8.8.8.8"]))
    result = _resolve_host("example.com")
    assert result == [ipaddress.ip_address("1.1.1.1"), ipaddress.ip_address("8.8.8.8")]


def test_resolve_host_skips_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _ga(["1.1.1.1", "garbage"]))
    assert _resolve_host("example.com") == [ipaddress.ip_address("1.1.1.1")]


def test_resolve_host_gaierror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **k: Any) -> list[Any]:
        raise socket.gaierror("no dns")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    assert _resolve_host("nope.invalid") == []


# ── _resolve_host_async ───────────────────────────────────────────


async def test_resolve_host_async_success(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=_ga(["93.184.216.34", "93.184.216.34"])))
    result = await _resolve_host_async("example.com")
    assert result == [ipaddress.ip_address("93.184.216.34")]


async def test_resolve_host_async_skips_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=_ga(["garbage", "1.1.1.1"])))
    assert await _resolve_host_async("example.com") == [ipaddress.ip_address("1.1.1.1")]


async def test_resolve_host_async_gaierror(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(side_effect=socket.gaierror("dns")))
    assert await _resolve_host_async("nope.invalid") == []


# ── is_private_url remaining branches ─────────────────────────────


def test_is_private_url_non_http_scheme() -> None:
    assert is_private_url("ftp://example.com") is True


def test_is_private_url_no_dns_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_resolve_host", lambda host: [])
    assert is_private_url("http://example.com") is True


def test_is_private_url_private_via_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_resolve_host", lambda host: [ipaddress.ip_address("10.1.2.3")])
    assert is_private_url("http://internal.example.com") is True


def test_is_private_url_resolution_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(host: str) -> list[Any]:
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(ssrf, "_resolve_host", _boom)
    assert is_private_url("http://example.com") is True


def test_is_private_url_local_tld(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_resolve_host", lambda host: [ipaddress.ip_address("1.1.1.1")])
    assert is_private_url("http://host.internal") is True


def test_is_private_url_public_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_resolve_host", lambda host: [ipaddress.ip_address("1.1.1.1")])
    assert is_private_url("http://example.com") is False


# ── validate_url_async ────────────────────────────────────────────


async def test_validate_url_async_invalid_scheme() -> None:
    assert await validate_url_async("ftp://example.com") == "Invalid scheme: ftp"


async def test_validate_url_async_missing_host() -> None:
    assert await validate_url_async("http:///path") == "Missing hostname"


async def test_validate_url_async_direct_private_ip() -> None:
    result = await validate_url_async("http://10.0.0.1/")
    assert result is not None and "private IP" in result


async def test_validate_url_async_direct_public_ip() -> None:
    assert await validate_url_async("http://8.8.8.8/") is None


async def test_validate_url_async_ghost_blocks_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=True)
    result = await validate_url_async("http://example.com")
    assert result is not None and "Ghost mode" in result


async def test_validate_url_async_resolve_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=False)
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[]))
    result = await validate_url_async("http://example.com")
    assert result == "Failed to resolve hostname: example.com"


async def test_validate_url_async_resolves_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=False)
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[ipaddress.ip_address("192.168.0.5")]))
    result = await validate_url_async("http://example.com")
    assert result is not None and "private IP" in result


async def test_validate_url_async_resolves_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=False)
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[ipaddress.ip_address("1.1.1.1")]))
    assert await validate_url_async("http://example.com") is None


@pytest.mark.parametrize(
    "ip",
    ["0.0.0.1", "100.64.0.1", "198.18.0.1", "198.19.255.254", "192.0.0.1", "240.0.0.1", "169.254.169.254"],
)
async def test_validate_url_async_extended_private_ranges(ip: str) -> None:
    result = await validate_url_async(f"http://{ip}/")
    assert result is not None and "private IP" in result


async def test_validate_url_async_ghost_allows_private_literal(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=True)
    assert await validate_url_async("http://127.0.0.1:8080/") is None


async def test_validate_url_async_ghost_rejects_mixed_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=True)
    monkeypatch.setattr(
        ssrf,
        "_resolve_host_async",
        AsyncMock(return_value=[ipaddress.ip_address("10.0.0.5"), ipaddress.ip_address("1.1.1.1")]),
    )
    result = await validate_url_async("http://example.com")
    assert result is not None and "Ghost mode" in result


# ── SSRFSafeTransport ─────────────────────────────────────────────


async def test_transport_public_ip_calls_super(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200)
    super_handle = AsyncMock(return_value=resp)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", super_handle)
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://8.8.8.8/")
    assert await transport.handle_async_request(request) is resp


async def test_transport_hostname_no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[]))
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://example.com/")
    with pytest.raises(httpx.ConnectError, match="Failed to resolve"):
        await transport.handle_async_request(request)


async def test_transport_hostname_resolves_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[ipaddress.ip_address("10.0.0.2")]))
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://evil.example/")
    with pytest.raises(httpx.ConnectError, match="private IP"):
        await transport.handle_async_request(request)


async def test_transport_hostname_pins_public(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200)
    sent: dict[str, Any] = {}

    async def _record(_self: Any, request: httpx.Request) -> httpx.Response:
        sent["url"] = request.url
        return resp

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _record)
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]))
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://example.com/")
    assert await transport.handle_async_request(request) is resp
    assert sent["url"].host == "93.184.216.34"
    # The wire target is the pin; the caller keeps the name it asked for.
    assert request.url.host == "example.com"


async def test_transport_https_pinning_keeps_host_port_and_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200)
    sent: dict[str, Any] = {}

    async def _record(_self: Any, request: httpx.Request) -> httpx.Response:
        sent["url"] = request.url
        sent["host"] = request.headers["host"]
        sent["sni"] = request.extensions.get("sni_hostname")
        return resp

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _record)
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]))
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "https://example.com:8443/status")
    assert await transport.handle_async_request(request) is resp
    assert sent["url"].host == "93.184.216.34"
    assert sent["url"].port == 8443
    # Virtual hosting and the TLS handshake are keyed on the name, not the pinned address.
    assert sent["host"] == "example.com:8443"
    assert sent["sni"] == "example.com"
    assert request.url.host == "example.com"


async def test_transport_keeps_caller_host_header(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = httpx.Response(200)
    super_handle = AsyncMock(return_value=resp)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", super_handle)
    monkeypatch.setattr(ssrf, "_resolve_host_async", AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]))
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "https://example.com/", headers={"Host": "vhost.example"})
    assert await transport.handle_async_request(request) is resp
    assert super_handle.await_args is not None
    sent_request = super_handle.await_args.args[0]
    assert sent_request.headers["host"] == "vhost.example"


# ── _materialize ──────────────────────────────────────────────────


async def test_materialize_within_limit() -> None:
    request = httpx.Request("GET", "http://example.com")
    monkey_resp: Any = _SpyResponse(status=200, chunks=[b"he", b"llo"], request=request)
    out = await _materialize(monkey_resp, max_bytes=100)
    assert out.content == b"hello"
    assert out.status_code == 200


async def test_materialize_exceeds_limit() -> None:
    request = httpx.Request("GET", "http://example.com")
    monkey_resp: Any = _SpyResponse(status=200, chunks=[b"x" * 60], request=request)
    with pytest.raises(ValueError, match="exceeds"):
        await _materialize(monkey_resp, max_bytes=10)


class _SpyResponse:
    def __init__(self, *, status: int, chunks: list[bytes], request: httpx.Request) -> None:
        self.status_code = status
        self.headers = httpx.Headers()
        self.request = request
        self.extensions: dict[str, Any] = {}
        self._chunks = chunks

    async def aiter_bytes(self) -> Any:
        for c in self._chunks:
            yield c


# ── safe_http_request ─────────────────────────────────────────────


async def test_safe_http_request_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def request(self, *, url: str, **kwargs: Any) -> httpx.Response:
            captured["url"] = url
            return httpx.Response(200, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    resp = await safe_http_request("http://example.com")
    assert resp.status_code == 200
    assert captured["url"] == "http://example.com"


async def test_safe_http_request_redirect_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "http://example.com"

    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def request(self, *, url: str, **kwargs: Any) -> httpx.Response:
            req = httpx.Request("GET", url)
            return httpx.Response(302, headers={"Location": "http://10.0.0.1/"}, request=req)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value="URL resolves to a private IP range"))
    with pytest.raises(httpx.ConnectError, match="Redirect blocked"):
        await safe_http_request(url)


async def test_safe_http_request_redirect_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def request(self, *, url: str, **kwargs: Any) -> httpx.Response:
            req = httpx.Request("GET", url)
            return httpx.Response(302, headers={"Location": "http://other.example/"}, request=req)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))
    resp = await safe_http_request("http://example.com")
    assert resp.status_code == 302


async def test_safe_http_request_relative_redirect_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        async def request(self, *, url: str, **kwargs: Any) -> httpx.Response:
            req = httpx.Request("GET", url)
            return httpx.Response(302, headers={"Location": "/next"}, request=req)

    checked: AsyncMock = AsyncMock(return_value=None)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(ssrf, "validate_url_async", checked)
    await safe_http_request("http://example.com/start")
    assert checked.await_args is not None
    assert checked.await_args.args[0] == "http://example.com/next"


# ── safe_fetch_async ──────────────────────────────────────────────


async def test_safe_fetch_invalid_scheme() -> None:
    with pytest.raises(ValueError, match="Invalid scheme"):
        await safe_fetch_async("ftp://example.com")


async def test_safe_fetch_blocked_by_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value="URL resolves to a private IP range"))
    with pytest.raises(ValueError, match="URL blocked by SSRF"):
        await safe_fetch_async("http://example.com")


async def test_safe_fetch_malformed_url_passes_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    # scheme is http and validate passes, but the regex requires no backslash/space
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))
    with pytest.raises(ValueError, match="Invalid URL"):
        await safe_fetch_async("http://example.com/a\\b")


async def _stub_stream(monkeypatch: pytest.MonkeyPatch, responses: list[tuple[int, dict[str, str], bytes]]) -> list[str]:
    """Patch httpx.AsyncClient so client.stream yields canned responses in order."""
    it = iter(responses)
    requested: list[str] = []

    class _StreamCtx:
        def __init__(self, resp: httpx.Response) -> None:
            self._resp = resp

        async def __aenter__(self) -> httpx.Response:
            return self._resp

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: Any) -> _StreamCtx:
            requested.append(url)
            status, headers, body = next(it)
            req = httpx.Request(method, url)
            resp = httpx.Response(status, headers=headers, content=body, request=req)
            return _StreamCtx(resp)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return requested


async def test_safe_fetch_plain_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))
    await _stub_stream(monkeypatch, [(200, {}, b"body")])
    resp = await safe_fetch_async("http://example.com")
    assert resp.status_code == 200
    assert resp.content == b"body"


async def test_safe_fetch_follows_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))
    requested = await _stub_stream(
        monkeypatch,
        [(301, {"Location": "http://example.com/final"}, b""), (200, {}, b"final body")],
    )
    resp = await safe_fetch_async("http://example.com")
    assert resp.content == b"final body"
    assert requested[-1] == "http://example.com/final"


async def test_safe_fetch_redirect_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def _validate(url: str) -> str | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else "URL resolves to a private IP range"

    monkeypatch.setattr(ssrf, "validate_url_async", _validate)
    await _stub_stream(monkeypatch, [(302, {"Location": "http://10.0.0.1/"}, b"")])
    with pytest.raises(httpx.ConnectError, match="Redirect blocked"):
        await safe_fetch_async("http://example.com")


async def test_safe_fetch_post_redirect_becomes_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))
    methods: list[str] = []

    class _StreamCtx:
        def __init__(self, resp: httpx.Response) -> None:
            self._resp = resp

        async def __aenter__(self) -> httpx.Response:
            return self._resp

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: Any) -> _StreamCtx:
            methods.append(method)
            req = httpx.Request(method, url)
            if len(methods) == 1:
                resp = httpx.Response(302, headers={"Location": "http://example.com/final"}, request=req)
            else:
                resp = httpx.Response(200, content=b"ok", request=req)
            return _StreamCtx(resp)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    resp = await safe_fetch_async("http://example.com", method="POST", content=b"data")
    assert methods == ["POST", "GET"]
    assert resp.content == b"ok"


async def test_safe_fetch_too_many_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))

    class _StreamCtx:
        def __init__(self, resp: httpx.Response) -> None:
            self._resp = resp

        async def __aenter__(self) -> httpx.Response:
            return self._resp

        async def __aexit__(self, *exc: Any) -> None:
            return None

    class _Client:
        def __init__(self, **kw: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *exc: Any) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: Any) -> _StreamCtx:
            req = httpx.Request(method, url)
            resp = httpx.Response(302, headers={"Location": f"http://example.com/hop{len(url)}"}, request=req)
            return _StreamCtx(resp)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    with pytest.raises(ValueError, match="Too many redirects"):
        await safe_fetch_async("http://example.com", max_redirects=2)


def test_validate_url_ghost_allows_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, ghost=True)
    assert validate_url("http://127.0.0.1/") is None


async def test_safe_fetch_redirect_without_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssrf, "validate_url_async", AsyncMock(return_value=None))
    await _stub_stream(monkeypatch, [(304, {}, b"cached")])
    resp = await safe_fetch_async("http://example.com")
    assert resp.status_code == 304
    assert resp.content == b"cached"
