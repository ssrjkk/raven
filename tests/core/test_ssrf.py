from __future__ import annotations

from unittest.mock import patch

import pytest

from raven.core.security.ssrf import is_private_url, validate_url


def test_validate_url_blocks_private_ip():
    result = validate_url("http://10.0.0.1/admin")
    assert result is not None
    assert "private" in result.lower()


def test_validate_url_blocks_localhost():
    result = validate_url("http://127.0.0.1:8080/")
    assert result is not None


def test_validate_url_allows_public_ip():
    with patch("raven.core.config.get_settings") as mock_settings:
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
    with patch("raven.core.config.get_settings") as mock_settings:
        s = type("s", (), {"ghost_mode": True})()
        mock_settings.return_value = s
        result = validate_url("http://93.184.216.34/")
        assert result is not None
        assert "ghost" in result.lower()
