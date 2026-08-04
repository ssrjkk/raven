from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from raven.core.security.ssrf import safe_fetch_async, validate_url

PLUGIN_NAME = "browser"
PLUGIN_DESCRIPTION = "Browse the web, take screenshots, and search the internet"

_browser = None
_context = None
_lock = asyncio.Lock()


async def _ensure_browser():
    global _browser, _context
    async with _lock:
        if _context is not None:
            return _context
        try:
            from playwright.async_api import async_playwright

            p = await async_playwright().start()
            _browser = p
            _context = await p.chromium.launch(headless=True)
            return _context
        except Exception as e:
            logger.warning("Playwright not available, using httpx fallback: {}", e)
            return None


async def _cleanup():
    global _browser, _context
    async with _lock:
        if _browser:
            try:
                await _browser.stop()
            except Exception as e:
                logger.error("Browser cleanup error: {}", e)
            _browser = None
            _context = None


async def browse(url: str) -> str:
    """Fetch and extract text content from a URL. Args: url (str): Full URL to visit"""
    error = validate_url(url)
    if error:
        return f"Blocked: {error}"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        browser = await _ensure_browser()
        if browser:
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                final_url = page.url
                error = validate_url(final_url)
                if error:
                    return f"Blocked: redirect to restricted address ({error})"
                content: str = await page.evaluate("document.body.innerText")
                return content[:4000]
            finally:
                await page.close()
        resp = await safe_fetch_async(url, timeout=15.0)
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:4000]
    except ValueError as e:
        return f"Blocked: {e}"
    except Exception as e:
        logger.error("Browse failed: {}", e)
        return f"Error browsing {url}: {e}"


async def screenshot(url: str) -> str:
    """Take a screenshot of a URL and return as base64. Args: url (str): Full URL to screenshot"""
    error = validate_url(url)
    if error:
        return f"Blocked: {error}"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        browser = await _ensure_browser()
        if not browser:
            return "Screenshot requires Playwright with Chromium. Install: playwright install chromium"
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        try:
            await page.goto(url, timeout=15000, wait_until="domcontentloaded")
            final_url = page.url
            error = validate_url(final_url)
            if error:
                return f"Blocked: redirect to restricted address ({error})"
            import base64

            screenshot_bytes = await page.screenshot(full_page=False)
            b64 = base64.b64encode(screenshot_bytes).decode()
            return f"![Screenshot](data:image/png;base64,{b64})"
        finally:
            await page.close()
    except Exception as e:
        logger.error("Screenshot failed: {}", e)
        return f"Error screenshotting {url}: {e}"


async def search(query: str, max_results: int = 5) -> str:
    """Search the internet using DuckDuckGo. Args: query (str): Search query, max_results (int): Max results to return"""
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            results = []
            for result in soup.select(".result")[:max_results]:
                title_el = result.select_one(".result__title a")
                snippet_el = result.select_one(".result__snippet")
                if title_el:
                    title = title_el.get_text(strip=True)
                    link = title_el.get("href", "")
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    results.append(f"- [{title}]({link})\n  {snippet[:200]}")
            if results:
                return f"Search results for '{query}':\n" + "\n".join(results)
            return f"No results found for '{query}'."
    except Exception as e:
        logger.error("Search failed: {}", e)
        return f"Error searching: {e}"
