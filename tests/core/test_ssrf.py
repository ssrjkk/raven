from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from raven.core.security.ssrf import (
    SSRFSafeTransport,
    _is_private_ip,
    is_private_url,
    validate_url,
    validate_url_async,
)


def test_validate_url_blocks_private_ip():
    result = validate_url("http://10.0.0.1/admin")
    assert result is not None
    assert "private" in result.lower()


def test_validate_url_blocks_localhost():
    result = validate_url("http://127.0.0.1:8080/")
    assert result is not None


def test_validate_url_allows_public_ip():
    with patch("raven.core.security.ssrf.get_settings") as mock_settings:
        s = type("s", (), {"ghost_mode": False})()
        mock_settings.return_value = s
        result = validate_url("http://93.184.216.34/")
        assert result is None


def test_is_private_url_detects_localhost():
    assert is_private_url("http://localhost") is True
    assert is_private_url("http://127.0.0.1") is True
    assert is_private_url("http://0.0.0.0") is True


def test_is_private_url_detects_private_networks():
    assert is_private_url("http://192.168.1.1") is True
    assert is_private_url("http://172.16.0.1") is True


def test_validate_url_ghost_mode_blocks_external():
    with patch("raven.core.security.ssrf.get_settings") as mock_settings:
        s = type("s", (), {"ghost_mode": True})()
        mock_settings.return_value = s
        result = validate_url("http://93.184.216.34/")
        assert result is not None
        assert "ghost" in result.lower()


class TestIsPrivateIp:
    def test_loopback(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_rfc1918(self):
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("192.168.1.1") is True

    def test_aws_metadata(self):
        assert _is_private_ip("169.254.169.254") is True

    def test_public_ip(self):
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False


@pytest.mark.asyncio
async def test_validate_url_async_allows_public():
    with patch("raven.core.security.ssrf.get_settings") as mock_settings:
        s = type("s", (), {"ghost_mode": False})()
        mock_settings.return_value = s
        result = await validate_url_async("http://93.184.216.34/")
        assert result is None


@pytest.mark.asyncio
async def test_ssrf_transport_blocks_private_ip():
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://127.0.0.1/")
    with pytest.raises(httpx.ConnectError, match="private IP"):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_ssrf_transport_blocks_metadata():
    transport = SSRFSafeTransport()
    request = httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")
    with pytest.raises(httpx.ConnectError, match="private IP"):
        await transport.handle_async_request(request)
