from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from raven.tools.search import web_search, web_search_raw


class TestWebSearch:
    @pytest.fixture(autouse=True)
    def _mock_httpx(self):
        patcher = patch("raven.tools.search.httpx.AsyncClient")
        self.mock_client_cls = patcher.start()
        self.mock_client = AsyncMock()
        self.mock_client_cls.return_value.__aenter__.return_value = self.mock_client
        yield
        patcher.stop()

    def _make_response(self, html: str = "", status: int = 200) -> httpx.Response:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status
        resp.text = html
        resp.raise_for_status = MagicMock()
        resp.content = html.encode()
        return resp

    async def test_web_search_unknown_provider(self) -> None:
        result = await web_search("hello", provider="unknown")
        assert "Unknown provider" in result

    async def test_web_search_no_results(self) -> None:
        html = '<html><body><div class="results"></div></body></html>'
        resp = self._make_response(html)
        self.mock_client.get = AsyncMock(return_value=resp)
        result = await web_search("nonexistent")
        assert "No results" in result

    async def test_web_search_duckduckgo_returns_results(self) -> None:
        html = """
        <html><body>
          <div class="result">
            <div class="result__title"><a href="https://example.com">Example</a></div>
            <div class="result__snippet">This is an example snippet</div>
          </div>
        </body></html>
        """
        resp = self._make_response(html)
        self.mock_client.get = AsyncMock(return_value=resp)
        result = await web_search("test query")
        assert "Example" in result
        assert "example snippet" in result
        assert "duckduckgo" in result.lower()

    async def test_web_search_http_error(self) -> None:
        self.mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "500 error", request=MagicMock(), response=MagicMock()
        ))
        result = await web_search("test")
        assert "error" in result.lower()

    async def test_web_search_raw(self) -> None:
        resp = self._make_response("")
        self.mock_client.get = AsyncMock(return_value=resp)
        result = await web_search_raw("test")
        assert isinstance(result, list)

    async def test_web_search_raw_unknown_provider(self) -> None:
        result = await web_search_raw("test", provider="bad")
        assert result == [{"error": "Unknown provider 'bad'"}]

    async def test_web_search_googe_no_key(self) -> None:
        with patch("raven.tools.search._GOOGLE_SEARCH_API_KEY", ""):
            result = await web_search("test", provider="google")
            assert "not configured" in result

    async def test_web_search_brave_no_key(self) -> None:
        with patch("raven.tools.search._BRAVE_SEARCH_API_KEY", ""):
            result = await web_search("test", provider="brave")
            assert "not configured" in result

    async def test_web_search_bing_no_key(self) -> None:
        with patch("raven.tools.search._BING_SEARCH_API_KEY", ""):
            result = await web_search("test", provider="bing")
            assert "not configured" in result
