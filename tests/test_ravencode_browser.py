from __future__ import annotations

import sys
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ravencode.runtime.browser as browser_mod
from ravencode.runtime.browser import (
    _ensure_page,
    _validate_navigation_url,
    browser_click,
    browser_close,
    browser_evaluate,
    browser_get_html,
    browser_navigate,
    browser_screenshot,
    browser_type,
)


@pytest.fixture(autouse=True)
def reset_browser() -> Generator[None, None, None]:
    browser_mod._PAGE = None
    browser_mod._BROWSER = None
    browser_mod._BROWSER_CONTEXT = None
    yield
    browser_mod._PAGE = None
    browser_mod._BROWSER = None
    browser_mod._BROWSER_CONTEXT = None


def _fake_page() -> SimpleNamespace:
    page = SimpleNamespace()
    page.goto = AsyncMock(return_value=None)
    page.title = AsyncMock(return_value="My Title")
    page.click = AsyncMock(return_value=None)
    page.fill = AsyncMock(return_value=None)
    page.screenshot = AsyncMock(return_value=None)
    page.query_selector = AsyncMock(return_value=SimpleNamespace(inner_html=AsyncMock(return_value="<p>hi</p>")))
    page.evaluate = AsyncMock(return_value={"k": 1})
    page.close = AsyncMock(return_value=None)
    return page


class TestValidateUrl:
    def test_valid(self) -> None:
        assert _validate_navigation_url("https://example.com") is None
        assert _validate_navigation_url("http://example.com") is None

    def test_bad_scheme(self) -> None:
        result = _validate_navigation_url("file:///etc/passwd")
        assert result is not None
        assert "only http/https" in result

    def test_missing_host(self) -> None:
        result = _validate_navigation_url("https://")
        assert result is not None
        assert "missing hostname" in result


class TestEnsurePage:
    async def test_creates_and_reuses(self, monkeypatch) -> None:
        page = _fake_page()
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context))
        pw = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
        monkeypatch.setitem(
            sys.modules,
            "playwright.async_api",
            SimpleNamespace(async_playwright=lambda: SimpleNamespace(start=AsyncMock(return_value=pw))),
        )
        first = await _ensure_page()
        second = await _ensure_page()
        assert first is page
        assert second is page
        assert browser_mod._PAGE is page
        assert browser_mod._BROWSER is browser


class TestNavigate:
    async def test_denied(self) -> None:
        result = await browser_navigate("ftp://x")
        assert result == "[denied] browser_navigate: only http/https URLs are allowed, got 'ftp://'"

    async def test_success(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        result = await browser_navigate("https://example.com")
        assert result == "Navigated to https://example.com | Title: My Title"

    async def test_error(self) -> None:
        page = _fake_page()
        page.goto = AsyncMock(side_effect=RuntimeError("net fail"))
        browser_mod._PAGE = page
        result = await browser_navigate("https://example.com")
        assert result == "[error] browser_navigate: net fail"


class TestClick:
    async def test_success(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        assert await browser_click("#btn") == "Clicked: #btn"

    async def test_error(self) -> None:
        page = _fake_page()
        page.click = AsyncMock(side_effect=RuntimeError("no el"))
        browser_mod._PAGE = page
        assert await browser_click("#btn") == "[error] browser_click: no el"


class TestType:
    async def test_success(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        assert await browser_type("#in", "hello") == "Typed 'hello' into #in"

    async def test_long_text_truncated(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        text = "x" * 50
        result = await browser_type("#in", "x" * 100)
        assert result == f"Typed '{text}' into #in"

    async def test_error(self) -> None:
        page = _fake_page()
        page.fill = AsyncMock(side_effect=RuntimeError("boom"))
        browser_mod._PAGE = page
        assert await browser_type("#in", "t") == "[error] browser_type: boom"


class TestScreenshot:
    async def test_success(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        assert await browser_screenshot("shot.png") == "Screenshot saved to shot.png"

    async def test_error(self) -> None:
        page = _fake_page()
        page.screenshot = AsyncMock(side_effect=RuntimeError("boom"))
        browser_mod._PAGE = page
        assert await browser_screenshot() == "[error] browser_screenshot: boom"


class TestGetHtml:
    async def test_success(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        assert await browser_get_html("body") == "<p>hi</p>"

    async def test_not_found(self) -> None:
        page = _fake_page()
        page.query_selector = AsyncMock(return_value=None)
        browser_mod._PAGE = page
        assert await browser_get_html("#x") == "[error] selector '#x' not found"

    async def test_error(self) -> None:
        page = _fake_page()
        page.query_selector = AsyncMock(side_effect=RuntimeError("boom"))
        browser_mod._PAGE = page
        assert await browser_get_html("#x") == "[error] browser_get_html: boom"


class TestEvaluate:
    async def test_success(self) -> None:
        page = _fake_page()
        browser_mod._PAGE = page
        assert await browser_evaluate("1+1") == "{'k': 1}"

    async def test_error(self) -> None:
        page = _fake_page()
        page.evaluate = AsyncMock(side_effect=RuntimeError("boom"))
        browser_mod._PAGE = page
        assert await browser_evaluate("x") == "[error] browser_evaluate: boom"


class TestClose:
    async def test_closes_all(self) -> None:
        page = _fake_page()
        context = SimpleNamespace(close=AsyncMock(return_value=None))
        browser = SimpleNamespace(close=AsyncMock(return_value=None))
        browser_mod._PAGE = page
        browser_mod._BROWSER_CONTEXT = context
        browser_mod._BROWSER = browser
        assert await browser_close() == "Browser closed"
        page.close.assert_awaited_once()
        context.close.assert_awaited_once()
        browser.close.assert_awaited_once()
        assert browser_mod._PAGE is None

    async def test_close_error_warns(self) -> None:
        browser = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("boom")))
        browser_mod._PAGE = _fake_page()
        browser_mod._BROWSER = browser
        assert await browser_close() == "Browser closed"
        assert browser_mod._BROWSER is None

    async def test_close_when_none(self) -> None:
        assert await browser_close() == "Browser closed"
