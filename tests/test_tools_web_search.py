from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

import raven.tools.web_search as ws
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.web_search import (
    SearchProvider,
    SearchResult,
    WebSearchTool,
    _fmt,
    _get_tool,
    register_web_search_tools,
    web_search,
    web_search_structured,
)


class _Secret:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


class _Resp:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            req = httpx.Request("GET", "http://example.com")
            raise httpx.HTTPStatusError(
                f"Server error '{self.status_code}' for url '{req.url}'",
                request=req,
                response=httpx.Response(self.status_code, request=req),
            )


class _Client:
    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    def _next(self) -> _Resp:
        return self._responses.pop(0) if self._responses else _Resp()

    async def get(self, url: str, **kwargs: Any) -> _Resp:
        self.calls.append(("GET", url, kwargs))
        return self._next()

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        self.calls.append(("POST", url, kwargs))
        return self._next()

    async def aclose(self) -> None:
        self.closed = True


def _fake_settings(**overrides: Any) -> SimpleNamespace:
    data: dict[str, Any] = {
        "brave_search_api_key": _Secret("brave-key"),
        "perplexity_api_key": _Secret("pplx-key"),
        "google_search_api_key": _Secret("google-key"),
        "google_cse_id": "cse-id",
        "bing_search_api_key": _Secret("bing-key"),
        "tavily_search_api_key": _Secret("tavily-key"),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _install_client(monkeypatch: pytest.MonkeyPatch, *responses: _Resp) -> _Client:
    client = _Client(*responses)
    monkeypatch.setattr(ws, "httpx", SimpleNamespace(AsyncClient=lambda *args, **kwargs: client))
    return client


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    WebSearchTool._client = None
    ws._tool_instance = None
    monkeypatch.setattr(ws, "settings", _fake_settings())
    yield
    WebSearchTool._client = None
    ws._tool_instance = None


class TestSearchProvider:
    def test_values(self) -> None:
        assert [p.value for p in SearchProvider] == [
            "brave",
            "duckduckgo",
            "perplexity",
            "google",
            "bing",
            "tavily",
        ]


class TestSearchResult:
    def test_model(self) -> None:
        r = SearchResult(title="t", url="u", snippet="s", provider=SearchProvider.BRAVE)
        assert r.source == ""
        assert r.model_dump() == {
            "title": "t",
            "url": "u",
            "snippet": "s",
            "provider": "brave",
            "source": "",
        }


class TestClientGet:
    async def test_creates_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch)
        tool = WebSearchTool()
        assert (await tool._client_get()) is client  # type: ignore[comparison-overlap]
        assert tool._client is client  # type: ignore[comparison-overlap]

    async def test_reuses_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch)
        tool = WebSearchTool()
        first = await tool._client_get()
        second = await tool._client_get()
        assert first is second is client  # type: ignore[comparison-overlap]


class TestSearchDispatch:
    async def test_default_provider_is_duckduckgo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, text="<html></html>"))
        tool = WebSearchTool()
        results = await tool.search("q")
        assert results == []
        assert client.calls[0][1] == "https://html.duckduckgo.com/html/"

    async def test_routes_brave(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(
            monkeypatch, _Resp(200, {"web": {"results": [{"title": "t", "url": "u", "description": "d"}]}})
        )
        tool = WebSearchTool()
        results = await tool.search("q", provider=SearchProvider.BRAVE, max_results=5)
        assert results[0].provider == SearchProvider.BRAVE
        assert client.calls[0][1] == "https://api.search.brave.com/res/v1/web/search"

    async def test_routes_duckduckgo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, text="<html></html>"))
        tool = WebSearchTool()
        results = await tool.search("q", provider=SearchProvider.DUCKDUCKGO)
        assert results == []
        assert client.calls[0][1] == "https://html.duckduckgo.com/html/"

    async def test_routes_perplexity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {"choices": [{"message": {"content": ""}}]}))
        tool = WebSearchTool()
        results = await tool.search("q", provider=SearchProvider.PERPLEXITY)
        assert results == []
        assert client.calls[0][0] == "POST"
        assert client.calls[0][1] == "https://api.perplexity.ai/chat/completions"

    async def test_routes_google(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        results = await tool.search("q", provider=SearchProvider.GOOGLE)
        assert results == []
        assert client.calls[0][1] == "https://www.googleapis.com/customsearch/v1"

    async def test_routes_bing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        results = await tool.search("q", provider=SearchProvider.BING)
        assert results == []
        assert client.calls[0][1] == "https://api.bing.microsoft.com/v7.0/search"

    async def test_routes_tavily(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        results = await tool.search("q", provider=SearchProvider.TAVILY)
        assert results == []
        assert client.calls[0][1] == "https://api.tavily.com/search"

    async def test_unknown_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="Unknown provider"):
            await tool.search("q", provider=cast(SearchProvider, "unknown"))


class TestBrave:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(
            monkeypatch,
            _Resp(
                200,
                {"web": {"results": [{"title": "t1", "url": "u1", "description": "d1"}, {"title": "t2", "url": "u2"}]}},
            ),
        )
        tool = WebSearchTool()
        results = await tool._brave("q", 10)
        assert len(results) == 2
        assert results[0].provider == SearchProvider.BRAVE
        assert results[0].snippet == "d1"
        assert results[1].snippet == ""
        method, url, kwargs = client.calls[0]
        assert method == "GET"
        assert url == "https://api.search.brave.com/res/v1/web/search"
        assert kwargs["params"] == {"q": "q", "count": 10}
        assert kwargs["headers"]["X-Subscription-Token"] == "brave-key"

    async def test_count_capped_at_20(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {"web": {"results": []}}))
        tool = WebSearchTool()
        await tool._brave("q", 50)
        assert client.calls[0][2]["params"]["count"] == 20

    async def test_empty_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        assert await tool._brave("q", 10) == []

    async def test_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(brave_search_api_key=_Secret()))
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="BRAVE_SEARCH_API_KEY"):
            await tool._brave("q", 10)


class TestDuckduckgo:
    HTML = """
    <html><body>
      <div class="result">
        <div class="result__title"><a href="https://example.com/a">Title A</a></div>
        <a class="result__snippet">Snippet A</a>
      </div>
      <div class="result">
        <span class="result__snippet">no title here</span>
      </div>
      <div class="result">
        <div class="result__title"><a href="https://example.com/b">Title B</a></div>
      </div>
    </body></html>
    """

    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, text=self.HTML))
        tool = WebSearchTool()
        results = await tool._duckduckgo("q", 10)
        assert len(results) == 2
        assert results[0].title == "Title A"
        assert results[0].url == "https://example.com/a"
        assert results[0].snippet == "Snippet A"
        assert results[1].snippet == ""
        assert client.calls[0][2]["headers"]["User-Agent"] == "Mozilla/5.0"

    async def test_limits_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, text=self.HTML))
        tool = WebSearchTool()
        results = await tool._duckduckgo("q", 1)
        assert len(results) == 1

    async def test_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, text="<html><body></body></html>"))
        tool = WebSearchTool()
        assert await tool._duckduckgo("q", 10) == []

    async def test_result_without_title_link_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, text='<div class="result"><span class="result__snippet">x</span></div>'))
        tool = WebSearchTool()
        results = await tool._duckduckgo("q", 10)
        assert results == []
        assert client.calls[0][1] == "https://html.duckduckgo.com/html/"


class TestPerplexity:
    def _resp(self, content: str) -> _Resp:
        return _Resp(200, {"choices": [{"message": {"content": content}}]})

    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(
            monkeypatch,
            self._resp("intro line\n1. [Title](https://example.com/a) - description here\n\n2. [Title2](https://example.com/b) - more"),
        )
        tool = WebSearchTool()
        results = await tool._perplexity("q", 10)
        assert len(results) == 2
        assert results[0].title == "Title"
        assert results[0].url == "https://example.com/a"
        assert results[0].snippet == "description here"
        assert results[1].provider == SearchProvider.PERPLEXITY
        method, url, kwargs = client.calls[0]
        assert method == "POST"
        assert url == "https://api.perplexity.ai/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer pplx-key"
        assert kwargs["json"]["model"] == "sonar-pro"

    async def test_limits_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, self._resp("1. [a](u1) - d1\n2. [b](u2) - d2\n3. [c](u3) - d3"))
        tool = WebSearchTool()
        results = await tool._perplexity("q", 2)
        assert len(results) == 2

    async def test_falls_back_to_raw_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, self._resp("plain text without formatting"))
        tool = WebSearchTool()
        results = await tool._perplexity("q", 10)
        assert len(results) == 1
        assert results[0].title == "Perplexity Response"
        assert results[0].url == ""
        assert results[0].source == "perplexity"
        assert results[0].snippet == "plain text without formatting"

    async def test_empty_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, self._resp(""))
        tool = WebSearchTool()
        assert await tool._perplexity("q", 10) == []

    async def test_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(perplexity_api_key=_Secret()))
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="PERPLEXITY_API_KEY"):
            await tool._perplexity("q", 10)


class TestGoogle:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(
            monkeypatch,
            _Resp(200, {"items": [{"title": "t", "link": "u", "snippet": "s"}, {"title": "t2"}]}),
        )
        tool = WebSearchTool()
        results = await tool._google("q", 10)
        assert len(results) == 2
        assert results[0].provider == SearchProvider.GOOGLE
        assert results[0].snippet == "s"
        assert results[1].snippet == ""
        assert client.calls[0][2]["params"] == {"key": "google-key", "cx": "cse-id", "q": "q", "num": 10}

    async def test_num_capped_at_10(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        await tool._google("q", 50)
        assert client.calls[0][2]["params"]["num"] == 10

    async def test_empty_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        assert await tool._google("q", 10) == []

    async def test_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(google_search_api_key=_Secret()))
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="GOOGLE_SEARCH_API_KEY"):
            await tool._google("q", 10)

    async def test_missing_cse_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(google_cse_id=""))
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="GOOGLE_SEARCH_API_KEY"):
            await tool._google("q", 10)


class TestBing:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(
            monkeypatch,
            _Resp(200, {"webPages": {"value": [{"name": "t", "url": "u", "snippet": "s"}]}}),
        )
        tool = WebSearchTool()
        results = await tool._bing("q", 10)
        assert len(results) == 1
        assert results[0].provider == SearchProvider.BING
        assert client.calls[0][2]["headers"]["Ocp-Apim-Subscription-Key"] == "bing-key"
        assert client.calls[0][2]["params"] == {"q": "q", "count": 10}

    async def test_count_capped_at_10(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        await tool._bing("q", 50)
        assert client.calls[0][2]["params"]["count"] == 10

    async def test_empty_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        assert await tool._bing("q", 10) == []

    async def test_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(bing_search_api_key=_Secret()))
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="BING_SEARCH_API_KEY"):
            await tool._bing("q", 10)


class TestTavily:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {"results": [{"title": "t", "url": "u", "content": "c"}]}))
        tool = WebSearchTool()
        results = await tool._tavily("q", 10)
        assert len(results) == 1
        assert results[0].provider == SearchProvider.TAVILY
        assert client.calls[0][0] == "POST"
        assert client.calls[0][2]["json"] == {"api_key": "tavily-key", "query": "q", "max_results": 10, "search_depth": "basic"}

    async def test_max_results_capped_at_10(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        await tool._tavily("q", 50)
        assert client.calls[0][2]["json"]["max_results"] == 10

    async def test_empty_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {}))
        tool = WebSearchTool()
        assert await tool._tavily("q", 10) == []

    async def test_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(tavily_search_api_key=_Secret()))
        tool = WebSearchTool()
        with pytest.raises(ValueError, match="TAVILY_SEARCH_API_KEY"):
            await tool._tavily("q", 10)


class TestSearchWithFailover:
    async def test_success_on_first_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"web": {"results": [{"title": "t", "url": "u", "description": "d"}]}}))
        tool = WebSearchTool()
        results = await tool.search_with_failover("q", max_results=5)
        assert len(results) == 1
        assert results[0].provider == SearchProvider.BRAVE

    async def test_falls_through_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(
            monkeypatch,
            _Resp(500),
            _Resp(200, text="<html><body></body></html>"),
        )
        tool = WebSearchTool()
        results = await tool.search_with_failover("q", providers=[SearchProvider.BRAVE, SearchProvider.DUCKDUCKGO])
        assert results == []

    async def test_all_providers_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(500), _Resp(500))
        tool = WebSearchTool()
        with pytest.raises(RuntimeError, match="All providers failed"):
            await tool.search_with_failover("q", providers=[SearchProvider.BRAVE, SearchProvider.BING])

    async def test_empty_provider_list_uses_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"web": {"results": []}}))
        tool = WebSearchTool()
        results = await tool.search_with_failover("q", providers=[])
        assert results == []


class TestClose:
    async def test_closes_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(monkeypatch)
        tool = WebSearchTool()
        await tool._client_get()
        assert tool._client is not None
        await tool.close()
        assert client.closed is True
        assert tool._client is None

    async def test_noop_without_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        tool = WebSearchTool()
        await tool.close()


class TestFmt:
    def test_empty(self) -> None:
        assert _fmt([]) == "No results found."

    def test_with_results(self) -> None:
        r1 = SearchResult(title="t", url="u", snippet="s", provider=SearchProvider.BRAVE)
        r2 = SearchResult(title="t2", url="u2", snippet="", provider=SearchProvider.DUCKDUCKGO)
        out = _fmt([r1, r2])
        assert out.splitlines()[0] == "1. [t](u)"
        assert "   s" in out
        assert "   source: brave" in out
        assert "2. [t2](u2)" in out

    def test_long_snippet_truncated(self) -> None:
        r = SearchResult(title="t", url="u", snippet="x" * 500, provider=SearchProvider.BING)
        out = _fmt([r])
        assert "x" * 200 in out
        assert "x" * 201 not in out


class TestGetTool:
    def test_singleton(self) -> None:
        assert _get_tool() is _get_tool()

    def test_new_instance_after_reset(self) -> None:
        first = _get_tool()
        ws._tool_instance = None
        second = _get_tool()
        assert first is not second


class TestWebSearch:
    async def test_success_default_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _install_client(
            monkeypatch,
            _Resp(
                200,
                text='<div class="result"><div class="result__title"><a href="https://e.com/a">T</a></div><a class="result__snippet">S</a></div>',
            ),
        )
        result = await web_search("hello")
        assert "1. [T](https://e.com/a)" in result
        assert "S" in result
        assert client.calls[0][1] == "https://html.duckduckgo.com/html/"

    async def test_success_google_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"items": [{"title": "t", "link": "u", "snippet": "s"}]}))
        result = await web_search("hello", provider=SearchProvider.GOOGLE, max_results=3)
        assert "1. [t](u)" in result

    async def test_no_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"web": {"results": []}}))
        result = await web_search("hello", provider=SearchProvider.BRAVE)
        assert result == "No results found."

    async def test_failover(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"web": {"results": []}}))
        result = await web_search("hello", failover=True)
        assert result == "No results found."

    async def test_value_error_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        result = await web_search("hello", provider="not-a-provider")
        assert result.startswith("Search error:")

    async def test_missing_key_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch)
        monkeypatch.setattr(ws, "settings", _fake_settings(brave_search_api_key=_Secret()))
        result = await web_search("hello", provider=SearchProvider.BRAVE)
        assert result == "Search error: BRAVE_SEARCH_API_KEY env var required"

    async def test_generic_exception_returns_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(500))
        result = await web_search("hello", provider=SearchProvider.BRAVE)
        assert result.startswith("Search failed:")
        assert "Server error '500'" in result


class TestWebSearchStructured:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"items": [{"title": "t", "link": "u", "snippet": "s"}]}))
        result = await web_search_structured("hello", provider=SearchProvider.GOOGLE)
        assert result == [{"title": "t", "url": "u", "snippet": "s", "provider": "google", "source": ""}]

    async def test_failover(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(200, {"web": {"results": []}}))
        result = await web_search_structured("hello", failover=True)
        assert result == []

    async def test_exception_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_client(monkeypatch, _Resp(500))
        result = await web_search_structured("hello", provider=SearchProvider.BRAVE)
        assert len(result) == 1
        assert "error" in result[0]
        assert "Server error '500'" in result[0]["error"]


class TestRegisterWebSearchTools:
    def test_registers_tools(self) -> None:
        registry = ToolRegistry()
        register_web_search_tools(registry)
        assert registry.count == 2
        spec_search = registry.get("web_search")
        spec_structured = registry.get("web_search_structured")
        assert spec_search is not None
        assert spec_structured is not None
        assert spec_search.category == "web"
        assert spec_structured.category == "web"
        assert spec_search.handler is web_search
        assert spec_structured.handler is web_search_structured
        assert spec_search.timeout == 30
        assert spec_structured.timeout == 30
