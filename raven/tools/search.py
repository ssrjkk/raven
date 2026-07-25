from __future__ import annotations

import os
from typing import Any, cast

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
_GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID", "")
_BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
_BING_SEARCH_API_KEY = os.environ.get("BING_SEARCH_API_KEY", "")


async def _duckduckgo(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(
            f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}", headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for result in soup.select(".result")[:max_results]:
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")
            if title_el:
                results.append(
                    {
                        "title": title_el.get_text(strip=True),
                        "url": title_el.get("href", ""),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    }
                )
        return results


async def _google(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    api_key = _GOOGLE_SEARCH_API_KEY
    cse_id = _GOOGLE_CSE_ID
    if not api_key or not cse_id:
        raise ValueError("GOOGLE_SEARCH_API_KEY and GOOGLE_CSE_ID env vars required")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cse_id, "q": query, "num": min(max_results, 10)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")}
            for item in data.get("items", [])[:max_results]
        ]


async def _brave(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    api_key = _BRAVE_SEARCH_API_KEY
    if not api_key:
        raise ValueError("BRAVE_SEARCH_API_KEY env var required")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": api_key},
            params={"q": query, "count": min(max_results, 10)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("description", "")}
            for item in data.get("web", {}).get("results", [])[:max_results]
        ]


async def _bing(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    api_key = _BING_SEARCH_API_KEY
    if not api_key:
        raise ValueError("BING_SEARCH_API_KEY env var required")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": api_key},
            params={"q": query, "count": min(max_results, 10)},
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": item.get("name", ""), "url": item.get("url", ""), "snippet": item.get("snippet", "")}
            for item in data.get("webPages", {}).get("value", [])[:max_results]
        ]


_PROVIDERS: dict[str, Any] = {
    "duckduckgo": _duckduckgo,
    "google": _google,
    "brave": _brave,
    "bing": _bing,
}


async def web_search(query: str, max_results: int = 5, provider: str = "duckduckgo") -> str:
    search_fn = _PROVIDERS.get(provider)
    if not search_fn:
        available = ", ".join(_PROVIDERS.keys())
        return f"Unknown provider '{provider}'. Available: {available}"
    try:
        results = await search_fn(query, max_results)
    except ValueError as e:
        return f"Provider '{provider}' not configured: {e}"
    except Exception as e:
        logger.error("Search failed ({}): {}", provider, e)
        return f"Search error with '{provider}': {e}"

    if not results:
        return f"No results found for '{query}'."

    lines = [f"Search results for '{query}' via {provider}:\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r['title']}]({r['url']})")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:200]}")
        lines.append("")
    return "\n".join(lines)


async def web_search_raw(query: str, max_results: int = 5, provider: str = "duckduckgo") -> list[dict[str, Any]]:
    search_fn = _PROVIDERS.get(provider)
    if not search_fn:
        return [{"error": f"Unknown provider '{provider}'"}]
    try:
        return cast("list[dict[str, Any]]", await search_fn(query, max_results))
    except Exception as e:
        return [{"error": str(e)}]


def register_search_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="web_search",
            description="Search the web using a configurable provider (duckduckgo, google, brave, bing)",
            parameters={
                "query": {"type": "string", "description": "Search query", "required": True},
                "max_results": {"type": "integer", "description": "Max results to return", "required": False},
                "provider": {
                    "type": "string",
                    "description": "Search provider (duckduckgo, google, brave, bing)",
                    "required": False,
                },
            },
            handler=web_search,
            category="web",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="web_search_raw",
            description="Search the web and return raw structured results (list of {title, url, snippet})",
            parameters={
                "query": {"type": "string", "description": "Search query", "required": True},
                "max_results": {"type": "integer", "description": "Max results to return", "required": False},
                "provider": {"type": "string", "description": "Search provider", "required": False},
            },
            handler=web_search_raw,
            category="web",
            timeout=30,
        )
    )
