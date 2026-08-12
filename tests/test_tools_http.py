from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.http import http_get, http_post, register_http_tools


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        location: str | None = None,
        redirect: bool = False,
        informational: bool = False,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = {"Location": location} if location else {}
        self.is_redirect = redirect
        self.is_informational = informational


def _make_client(*responses: FakeResponse) -> tuple[AsyncMock, list[tuple[str, str, dict[str, Any]]]]:
    client = AsyncMock()
    client.__aenter__.return_value = client
    calls: list[tuple[str, str, dict[str, Any]]] = []
    queue = list(responses)

    async def request(method: str, url: str, **kwargs: Any) -> FakeResponse:
        calls.append((method, url, kwargs))
        return queue.pop(0) if queue else FakeResponse()

    client.request = AsyncMock(side_effect=request)
    return client, calls


class TestHttpGet:
    async def test_get_success(self) -> None:
        client, calls = _make_client(FakeResponse(text="hello"))
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/")
        assert result == "hello"
        fake_httpx.AsyncClient.assert_called_once_with(timeout=30, follow_redirects=False)
        assert calls[0][0] == "GET"
        assert calls[0][1] == "https://example.com/"

    async def test_get_blocked_private_ip(self) -> None:
        result = await http_get("http://127.0.0.1/admin")
        assert "[blocked]" in result
        assert "private" in result.lower()

    async def test_post_blocked_private_ip(self) -> None:
        result = await http_post("http://192.168.1.1/x")
        assert "[blocked]" in result

    async def test_get_parses_headers(self) -> None:
        client, calls = _make_client(FakeResponse(text="ok"))
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/", headers="Content-Type: application/json\nX-Test: yes")
        assert result == "ok"
        assert calls[0][2]["headers"] == {"Content-Type": "application/json", "X-Test": "yes"}

    async def test_get_truncates_long_body(self) -> None:
        client, _ = _make_client(FakeResponse(text="x" * 25000))
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/")
        assert len(result) == 20000

    async def test_get_follows_redirect(self) -> None:
        client, calls = _make_client(
            FakeResponse(302, redirect=True, location="https://example.com/next"), FakeResponse(text="final")
        )
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/start")
        assert result == "final"
        assert len(calls) == 2
        assert calls[1][1] == "https://example.com/next"

    async def test_get_redirect_blocked(self) -> None:
        def validate(url: str) -> str | None:
            return "blocked by test" if "next" in url else None

        client, calls = _make_client(FakeResponse(302, redirect=True, location="https://example.com/next"))
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", side_effect=validate):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/start")
        assert result == "[blocked] redirect blocked: blocked by test"
        assert len(calls) == 1

    async def test_get_redirect_without_location(self) -> None:
        client, _ = _make_client(FakeResponse(302, redirect=True, location=None))
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/start")
        assert result == "[blocked] too many redirects"

    async def test_get_too_many_redirects(self) -> None:
        client, calls = _make_client(*[FakeResponse(302, redirect=True, location="https://example.com/n") for _ in range(6)])
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_get("https://example.com/start")
        assert result == "[blocked] too many redirects"
        assert len(calls) == 6


class TestHttpPost:
    async def test_post_success(self) -> None:
        client, calls = _make_client(FakeResponse(text="created"))
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_post("https://example.com/api", body='{"a": 1}', content_type="application/json")
        assert result == "created"
        assert calls[0][0] == "POST"
        assert calls[0][2]["content"] == '{"a": 1}'
        assert calls[0][2]["headers"] == {"Content-Type": "application/json"}

    async def test_post_302_redirect_becomes_get(self) -> None:
        client, calls = _make_client(
            FakeResponse(302, redirect=True, location="https://example.com/new"), FakeResponse(text="posted")
        )
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_post("https://example.com/start", body="payload")
        assert result == "posted"
        assert calls[1][0] == "GET"
        assert calls[1][1] == "https://example.com/new"
        assert "content" not in calls[1][2]

    async def test_post_301_redirect_becomes_get(self) -> None:
        client, calls = _make_client(
            FakeResponse(301, redirect=True, location="https://example.com/new"), FakeResponse(text="posted")
        )
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_post("https://example.com/start", body="payload")
        assert result == "posted"
        assert calls[1][0] == "GET"
        assert "content" not in calls[1][2]

    async def test_post_307_redirect_keeps_method(self) -> None:
        client, calls = _make_client(
            FakeResponse(307, redirect=True, location="https://example.com/new"), FakeResponse(text="posted")
        )
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_post("https://example.com/start", body="payload")
        assert result == "posted"
        assert calls[1][0] == "POST"
        assert calls[1][2]["content"] == "payload"

    async def test_post_follows_informational(self) -> None:
        client, calls = _make_client(
            FakeResponse(100, location="https://example.com/new", informational=True), FakeResponse(text="done")
        )
        with patch("raven.tools.http.httpx") as fake_httpx, patch("raven.tools.http.validate_url", return_value=None):
            fake_httpx.AsyncClient.return_value = client
            result = await http_post("https://example.com/start")
        assert result == "done"
        assert len(calls) == 2


class TestRegisterHttpTools:
    def test_registers_tools(self) -> None:
        registry = ToolRegistry()
        register_http_tools(registry)
        assert registry.count == 2
        spec_get = registry.get("http_get")
        spec_post = registry.get("http_post")
        assert spec_get is not None
        assert spec_post is not None
        assert spec_get.category == "web"
        assert spec_get.handler is http_get
        assert spec_post.handler is http_post
