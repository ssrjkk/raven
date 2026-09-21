from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.plugin_context import handle_capability


@pytest.mark.asyncio
async def test_cap_safe_http_get() -> None:
    with patch("raven.core.plugin_context.validate_url", return_value=None), patch(
        "raven.tools.http._fetch", new_callable=AsyncMock, return_value="response body"
    ):
        result = await handle_capability("test_plugin", "safe_http", {"method": "GET", "url": "https://example.com"})
        assert result == "response body"


@pytest.mark.asyncio
async def test_cap_safe_http_post() -> None:
    with patch("raven.core.plugin_context.validate_url", return_value=None), patch(
        "raven.tools.http._fetch", new_callable=AsyncMock, return_value="created"
    ):
        result = await handle_capability(
            "test_plugin", "safe_http", {"method": "POST", "url": "https://example.com", "body": '{"a":1}'}
        )
        assert result == "created"


@pytest.mark.asyncio
async def test_cap_safe_http_blocked_url() -> None:
    with patch("raven.core.plugin_context.validate_url", return_value="Blocked: internal IP"):
        result = await handle_capability("test_plugin", "safe_http", {"method": "GET", "url": "http://192.168.1.1"})
        assert result is not None
        assert "[blocked]" in result


@pytest.mark.asyncio
async def test_cap_safe_http_unsupported_method() -> None:
    with patch("raven.core.plugin_context.validate_url", return_value=None):
        result = await handle_capability("test_plugin", "safe_http", {"method": "DELETE", "url": "https://example.com"})
        assert result is not None
        assert "[error]" in result


@pytest.mark.asyncio
async def test_cap_safe_file_read() -> None:
    with patch("raven.tools.file.file_read", new_callable=AsyncMock, return_value="file content"):
        result = await handle_capability("test_plugin", "safe_file_read", {"path": "/tmp/test.txt"})
        assert result == "file content"


@pytest.mark.asyncio
async def test_cap_safe_file_write() -> None:
    with patch("raven.tools.file.file_write", new_callable=AsyncMock, return_value="written"):
        result = await handle_capability("test_plugin", "safe_file_write", {"path": "/tmp/out.txt", "content": "data"})
        assert result == "written"


@pytest.mark.asyncio
async def test_unknown_capability() -> None:
    result = await handle_capability("test_plugin", "unknown_cap", {})
    assert result is None
