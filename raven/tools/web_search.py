from __future__ import annotations

from enum import StrEnum
from typing import Any

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import BaseModel

from raven.core.config import settings
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


class SearchProvider(StrEnum):
    BRAVE = "brave"
    DUCKDUCKGO = "duckduckgo"
    PERPLEXITY = "perplexity"
    GOOGLE = "google"
    BING = "bing"
    TAVILY = "tavily"


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    provider: SearchProvider
    source: str = ""


class WebSearchTool:
    _client: httpx.AsyncClient | None = None

    async def _client_get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15, follow_redirects=True)
        return self._client

    async def search(
        self, query: str, provider: SearchProvider = SearchProvider.DUCKDUCKGO, max_results: int = 10
    ) -> list[SearchResult]:
        if provider == SearchProvider.BRAVE:
            return await self._brave(query, max_results)
        elif provider == SearchProvider.DUCKDUCKGO:
            return await self._duckduckgo(query, max_results)
        elif provider == SearchProvider.PERPLEXITY:
            return await self._perplexity(query, max_results)
        elif provider == SearchProvider.GOOGLE:
            return await self._google(query, max_results)
        elif provider == SearchProvider.BING:
            return await self._bing(query, max_results)
        elif provider == SearchProvider.TAVILY:
            return await self._tavily(query, max_results)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    async def search_with_failover(
        self, query: str, providers: list[SearchProvider] | None = None, max_results: int = 10
    ) -> list[SearchResult]:
        providers = providers or list(SearchProvider)
        last_error: str | None = None
        for provider in providers:
            try:
                return await self.search(query, provider=provider, max_results=max_results)
            except Exception as e:
                last_error = str(e)
                logger.warning("[web_search] {} failed: {}", provider.value, e)
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    async def _brave(self, query: str, max_results: int) -> list[SearchResult]:
        api_key = settings.brave_search_api_key
        if not api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY env var required")
        client = await self._client_get()
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key},
            params={"q": query, "count": min(max_results, 20)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchResult(title=item.get("title", ""), url=item.get("url", ""), snippet=item.get("description", ""), provider=SearchProvider.BRAVE)
            for item in data.get("web", {}).get("results", [])[:max_results]
        ]

    async def _duckduckgo(self, query: str, max_results: int) -> list[SearchResult]:
        client = await self._client_get()
        resp = await client.get(
            f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for result in soup.select(".result")[:max_results]:
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")
            if title_el:
                href = title_el.get("href", "")
                results.append(SearchResult(
                    title=title_el.get_text(strip=True),
                    url=str(href) if href else "",
                    snippet=snippet_el.get_text(strip=True) if snippet_el else "",
                    provider=SearchProvider.DUCKDUCKGO,
                ))
        return results

    async def _perplexity(self, query: str, max_results: int) -> list[SearchResult]:
        api_key = settings.perplexity_api_key
        if not api_key:
            raise ValueError("PERPLEXITY_API_KEY env var required")
        client = await self._client_get()
        resp = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "sonar-pro",
                "messages": [
                    {"role": "system", "content": "You are a research assistant. Provide search results with sources."},
                    {"role": "user", "content": f"Search for: {query}\n\nReturn the results as a numbered list with title, URL, and brief description for each result. Format each result as: 1. [Title](url) - description"},
                ],
                "max_tokens": 1024,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        results: list[SearchResult] = []
        import re
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(r"\d+\.\s+\[(.+?)\]\((.+?)\)\s*[-–—]\s*(.+)", line)
            if m:
                results.append(SearchResult(title=m.group(1), url=m.group(2), snippet=m.group(3), provider=SearchProvider.PERPLEXITY))
        if not results and content:
            results.append(SearchResult(title="Perplexity Response", url="", snippet=content[:500], provider=SearchProvider.PERPLEXITY, source="perplexity"))
        return results[:max_results]

    async def _google(self, query: str, max_results: int) -> list[SearchResult]:
        api_key = settings.google_search_api_key
        cse_id = settings.google_cse_id
        if not api_key or not cse_id:
            raise ValueError("GOOGLE_SEARCH_API_KEY and GOOGLE_CSE_ID env vars required")
        client = await self._client_get()
        resp = await client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cse_id, "q": query, "num": min(max_results, 10)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchResult(title=item.get("title", ""), url=item.get("link", ""), snippet=item.get("snippet", ""), provider=SearchProvider.GOOGLE)
            for item in data.get("items", [])[:max_results]
        ]

    async def _bing(self, query: str, max_results: int) -> list[SearchResult]:
        api_key = settings.bing_search_api_key
        if not api_key:
            raise ValueError("BING_SEARCH_API_KEY env var required")
        client = await self._client_get()
        resp = await client.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={"q": query, "count": min(max_results, 10)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchResult(title=item.get("name", ""), url=item.get("url", ""), snippet=item.get("snippet", ""), provider=SearchProvider.BING)
            for item in data.get("webPages", {}).get("value", [])[:max_results]
        ]

    async def _tavily(self, query: str, max_results: int) -> list[SearchResult]:
        api_key = settings.tavily_search_api_key
        if not api_key:
            raise ValueError("TAVILY_SEARCH_API_KEY env var required")
        client = await self._client_get()
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": min(max_results, 10), "search_depth": "basic"},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchResult(title=item.get("title", ""), url=item.get("url", ""), snippet=item.get("content", ""), provider=SearchProvider.TAVILY)
            for item in data.get("results", [])[:max_results]
        ]

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


_tool_instance: WebSearchTool | None = None


async def _get_tool() -> WebSearchTool:
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = WebSearchTool()
    return _tool_instance


def _fmt(results: list[SearchResult]) -> str:
    if not results:
        return "No results found."
    lines: list[str] = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.title}]({r.url})")
        if r.snippet:
            lines.append(f"   {r.snippet[:200]}")
        lines.append(f"   source: {r.provider.value}")
        lines.append("")
    return "\n".join(lines)


async def web_search(query: str, max_results: int = 10, provider: str = "duckduckgo", failover: bool = False) -> str:
    tool = await _get_tool()
    try:
        if failover:
            results = await tool.search_with_failover(query, max_results=max_results)
        else:
            results = await tool.search(query, provider=SearchProvider(provider), max_results=max_results)
        return _fmt(results)
    except ValueError as e:
        return f"Search error: {e}"
    except Exception as e:
        logger.error("[web_search] error: {}", e)
        return f"Search failed: {e}"


async def web_search_structured(query: str, max_results: int = 10, provider: str = "duckduckgo", failover: bool = False) -> list[dict[str, Any]]:
    tool = await _get_tool()
    try:
        if failover:
            results = await tool.search_with_failover(query, max_results=max_results)
        else:
            results = await tool.search(query, provider=SearchProvider(provider), max_results=max_results)
        return [r.model_dump() for r in results]
    except Exception as e:
        return [{"error": str(e)}]


def register_web_search_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(name="web_search", description="Search the web using a configurable provider. Supports: brave, duckduckgo, perplexity, google, bing, tavily. Optional failover tries providers in order until one succeeds.", parameters={
        "query": {"type": "string", "description": "Search query", "required": True},
        "max_results": {"type": "integer", "description": "Max results to return", "required": False},
        "provider": {"type": "string", "description": "Search provider: brave, duckduckgo, perplexity, google, bing, tavily", "required": False},
        "failover": {"type": "boolean", "description": "Auto-failover across all providers if one fails", "required": False},
    }, handler=web_search, category="web", timeout=30))
    registry.register(ToolSpec(name="web_search_structured", description="Search the web and return structured results as list of {title, url, snippet, provider}", parameters={
        "query": {"type": "string", "description": "Search query", "required": True},
        "max_results": {"type": "integer", "description": "Max results to return", "required": False},
        "provider": {"type": "string", "description": "Search provider", "required": False},
        "failover": {"type": "boolean", "description": "Auto-failover across all providers", "required": False},
    }, handler=web_search_structured, category="web", timeout=30))
