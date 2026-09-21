from __future__ import annotations

import asyncio

from loguru import logger

from raven.core.security.ssrf import safe_fetch_async, validate_url


async def _ddg_search(query: str, num_results: int) -> list[dict[str, str]] | None:
    try:
        from duckduckgo_search import DDGS

        def _search() -> list[dict[str, str]]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=num_results))

        results = await asyncio.to_thread(_search)
        return results if results else None
    except ImportError:
        return None
    except Exception as e:
        logger.debug("DDG search failed: {}, trying fallback", e)
        return None




async def _httpx_search(query: str, num_results: int) -> list[dict[str, str]] | None:
    try:
        import httpx
        from bs4 import BeautifulSoup

        url = f"https://html.duckduckgo.com/html/?q={_urlencode(query)}"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for i, link in enumerate(soup.select("a.result__a")):
            if i >= num_results:
                break
            title = str(link.get_text(strip=True))
            href_attr = link.get("href", "")
            href = str(href_attr) if href_attr else ""
            body_el = link.find_next("a", class_="result__snippet")
            body = str(body_el.get_text(strip=True)) if body_el else ""
            results.append({"title": title, "href": href, "body": body})
        return results if results else None
    except ImportError:
        return None
    except Exception as e:
        logger.debug("httpx search fallback failed: {}", e)
        return None




def _urlencode(q: str) -> str:
    import urllib.parse

    return urllib.parse.quote(q)




async def web_search(query: str, num_results: int = 5) -> str:
    results = await _ddg_search(query, num_results) or await _httpx_search(query, num_results)
    if not results:
        return "(no results)"
    return "\n\n".join(f"• {r.get('title', '')}\n  {r.get('body', '')[:200]}\n  {r.get('href', '')}" for r in results)




async def web_fetch(url: str) -> str:
    if not validate_url(url):
        return f"[denied] URL blocked by SSRF guard: {url}"
    try:
        resp = await safe_fetch_async(url, timeout=30.0, headers={"User-Agent": "Raven/1.0"})
        resp.raise_for_status()
        return resp.text[:50_000]
    except ValueError as exc:
        logger.warning("web_fetch blocked: {}", exc)
        return f"[denied] URL blocked by SSRF guard: {exc}"
    except Exception as exc:
        logger.exception("web_fetch failed")
        return f"[error] web_fetch: {exc}"
