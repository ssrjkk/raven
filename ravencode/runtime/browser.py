from __future__ import annotations

from typing import Any

_BROWSER: Any = None
_BROWSER_CONTEXT: Any = None
_PAGE: Any = None


async def _ensure_page() -> Any:
    global _BROWSER, _BROWSER_CONTEXT, _PAGE
    if _PAGE is None:
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        _BROWSER = await p.chromium.launch(headless=True)
        _BROWSER_CONTEXT = await _BROWSER.new_context()
        _PAGE = await _BROWSER_CONTEXT.new_page()
    return _PAGE


async def browser_navigate(url: str) -> str:
    try:
        page = await _ensure_page()
        await page.goto(url, timeout=30000)
        title = await page.title()
        return f"Navigated to {url} | Title: {title}"
    except Exception as exc:
        return f"[error] browser_navigate: {exc}"


async def browser_click(selector: str) -> str:
    try:
        page = await _ensure_page()
        await page.click(selector, timeout=10000)
        return f"Clicked: {selector}"
    except Exception as exc:
        return f"[error] browser_click: {exc}"


async def browser_type(selector: str, text: str) -> str:
    try:
        page = await _ensure_page()
        await page.fill(selector, text, timeout=10000)
        return f"Typed '{text[:50]}' into {selector}"
    except Exception as exc:
        return f"[error] browser_type: {exc}"


async def browser_screenshot(path: str = "screenshot.png") -> str:
    try:
        page = await _ensure_page()
        await page.screenshot(path=path, full_page=True)
        return f"Screenshot saved to {path}"
    except Exception as exc:
        return f"[error] browser_screenshot: {exc}"


async def browser_get_html(selector: str = "body") -> str:
    try:
        page = await _ensure_page()
        el = await page.query_selector(selector)
        if not el:
            return f"[error] selector '{selector}' not found"
        html = await el.inner_html()
        return html[:10000]  # type: ignore[no-any-return]
    except Exception as exc:
        return f"[error] browser_get_html: {exc}"


async def browser_evaluate(script: str) -> str:
    try:
        page = await _ensure_page()
        result = await page.evaluate(script)
        return str(result)[:5000]
    except Exception as exc:
        return f"[error] browser_evaluate: {exc}"


async def browser_close() -> str:
    global _BROWSER, _BROWSER_CONTEXT, _PAGE
    try:
        if _PAGE:
            await _PAGE.close()
        if _BROWSER_CONTEXT:
            await _BROWSER_CONTEXT.close()
        if _BROWSER:
            await _BROWSER.close()
    except Exception:
        pass
    _PAGE = None
    _BROWSER_CONTEXT = None
    _BROWSER = None
    return "Browser closed"
