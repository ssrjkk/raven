from __future__ import annotations

import asyncio
import base64
import socket
import sys
import types
import webbrowser
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

import raven.tools.browser as browser_mod
from raven.core.task_engine.tool_registry import ToolRegistry


@pytest.fixture(autouse=True)
def _browser_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    async def _noop_sleep(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    yield
    browser_mod._agent = None
    browser_mod._browser_instance = None
    browser_mod._browser_context = None


class _FakeElement:
    def __init__(self, data: bytes = b"\x89PNG-ELEMENT") -> None:
        self.screenshot = AsyncMock(return_value=data)


class _FakePage:
    def __init__(self, **kwargs: Any) -> None:
        self.url = kwargs.get("url", "https://example.com/")
        self.context = SimpleNamespace(cookies=AsyncMock(return_value=kwargs.get("cookies", [])))
        self.title = AsyncMock(return_value=kwargs.get("title", "Example Page"))
        self.evaluate = AsyncMock(return_value=kwargs.get("eval_result", "page eval result"))
        self.wait_for_selector = AsyncMock(return_value=kwargs.get("element", _FakeElement()))
        self.click = AsyncMock(return_value=None)
        self.fill = AsyncMock(return_value=None)
        self.type = AsyncMock(return_value=None)
        self.select_option = AsyncMock(return_value=None)
        self.inner_text = AsyncMock(return_value=kwargs.get("text", "inner text"))
        self.inner_html = AsyncMock(return_value=kwargs.get("html", "<p>inner html</p>"))
        self.screenshot = AsyncMock(return_value=kwargs.get("shot", b"\x89PNG-FULL"))
        self.goto = AsyncMock(return_value=None)
        self.close = AsyncMock(return_value=None)


def _install_browser(monkeypatch: pytest.MonkeyPatch, page: _FakePage) -> SimpleNamespace:
    fake_browser = SimpleNamespace(new_page=AsyncMock(return_value=page))
    monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=fake_browser))
    return fake_browser


def _install_agent(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    agent = SimpleNamespace(
        fill_form=AsyncMock(return_value="filled form"),
        extract_table=AsyncMock(return_value='{"headers": []}'),
        start_network_intercept=AsyncMock(return_value="intercept started"),
        stop_network_intercept=AsyncMock(return_value="intercept stopped"),
        get_intercepted_requests=AsyncMock(return_value="request list"),
        get_intercepted_responses=AsyncMock(return_value="response list"),
        new_tab=AsyncMock(return_value="new tab"),
        close_tab=AsyncMock(return_value="closed tab"),
        switch_tab=AsyncMock(return_value="switched tab"),
        list_tabs=AsyncMock(return_value="tab list"),
        set_download_handler=AsyncMock(return_value="handler set"),
        get_download=AsyncMock(return_value="downloaded"),
        set_extra_http_headers=AsyncMock(return_value="headers set"),
        wait_for_function=AsyncMock(return_value="function done"),
        wait_for_navigation=AsyncMock(return_value="navigation done"),
        get_title=AsyncMock(return_value="Agent Title"),
        get_url=AsyncMock(return_value="https://example.com/"),
        set_cookies=AsyncMock(return_value="cookies set"),
        clear_cookies=AsyncMock(return_value="cookies cleared"),
    )
    monkeypatch.setattr(browser_mod, "_get_agent", AsyncMock(return_value=agent))
    return agent


def _dns_fail(*_: Any, **__: Any) -> Any:
    raise socket.gaierror("dns down")


def _oserror(*_: Any, **__: Any) -> Any:
    raise OSError("network down")


class TestValidateUrl:
    def test_missing_hostname(self) -> None:
        with pytest.raises(ValueError, match="missing hostname"):
            browser_mod._validate_url("http:///path")

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://10.0.0.1",
            "http://172.16.0.1",
            "http://192.168.1.1",
            "http://[::1]/x",
            "http://[fc00::1]/x",
        ],
    )
    def test_private_ip_literal(self, url: str) -> None:
        with pytest.raises(ValueError, match="private IP"):
            browser_mod._validate_url(url)

    def test_public_ip_literal(self) -> None:
        browser_mod._validate_url("http://8.8.8.8/x")  # must not raise

    def test_localhost_blocked(self) -> None:
        with pytest.raises(ValueError, match="hostname localhost"):
            browser_mod._validate_url("http://localhost/")

    def test_zero_zero_zero_zero_bypasses_guard(self) -> None:
        browser_mod._validate_url("http://0.0.0.0/")  # must not raise

    def test_resolves_to_private(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [("AF_INET", "SOCK_STREAM", 6, "", ("10.0.0.5", 0))])
        with pytest.raises(ValueError, match="resolves to private IP"):
            browser_mod._validate_url("http://example.com")

    def test_resolves_to_public(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [("AF_INET", "SOCK_STREAM", 6, "", ("8.8.4.4", 0))])
        browser_mod._validate_url("http://example.com")  # must not raise

    def test_resolves_to_ipv6_private(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *a, **k: [("AF_INET6", "SOCK_STREAM", 6, "", ("::1", 0, 0, 0))],
        )
        with pytest.raises(ValueError, match="resolves to private IP"):
            browser_mod._validate_url("http://example.com")

    def test_resolves_public_then_private(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addrs = [
            ("AF_INET", "SOCK_STREAM", 6, "", ("8.8.8.8", 0)),
            ("AF_INET", "SOCK_STREAM", 6, "", ("192.168.0.5", 0)),
        ]
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: addrs)
        with pytest.raises(ValueError, match="resolves to private IP"):
            browser_mod._validate_url("http://example.com")

    def test_dns_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _dns_fail)
        browser_mod._validate_url("http://example.com")  # must not raise

    def test_os_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _oserror)
        browser_mod._validate_url("http://example.com")  # must not raise


class TestGetPlaywright:
    async def test_cached_context(self) -> None:
        cached = object()
        browser_mod._browser_context = cached  # type: ignore[assignment]
        assert await browser_mod._get_playwright() is cached

    async def test_launch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_browser = object()
        launch = AsyncMock(return_value=fake_browser)
        playwright_obj = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        factory = Mock(return_value=SimpleNamespace(start=AsyncMock(return_value=playwright_obj)))
        mod = types.ModuleType("playwright.async_api")
        setattr(mod, "async_playwright", factory)  # noqa: B010
        monkeypatch.setitem(sys.modules, "playwright.async_api", mod)
        assert await browser_mod._get_playwright() is fake_browser
        assert browser_mod._browser_instance is playwright_obj  # type: ignore[comparison-overlap]
        assert browser_mod._browser_context is fake_browser
        launch.assert_awaited_once_with(headless=True)

    async def test_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "playwright.async_api", None)
        assert await browser_mod._get_playwright() is None


class TestClosePlaywright:
    async def test_stop(self) -> None:
        browser_mod._browser_instance = SimpleNamespace(stop=AsyncMock())  # type: ignore[assignment]
        browser_mod._browser_context = object()  # type: ignore[assignment]
        await browser_mod._close_playwright()
        assert browser_mod._browser_instance is None
        assert browser_mod._browser_context is None

    async def test_stop_error(self) -> None:
        browser_mod._browser_instance = SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("boom")))  # type: ignore[assignment]
        browser_mod._browser_context = object()  # type: ignore[assignment]
        await browser_mod._close_playwright()
        assert browser_mod._browser_instance is None
        assert browser_mod._browser_context is None

    async def test_no_instance(self) -> None:
        await browser_mod._close_playwright()
        assert browser_mod._browser_instance is None


class TestGetAgent:
    async def test_creates_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Agent:
            def __init__(self, headless: bool) -> None:
                self.headless = headless
                self.start = AsyncMock()

        monkeypatch.setattr(browser_mod, "BrowserAgent", _Agent)
        agent = await browser_mod._get_agent()
        assert agent is not None
        assert agent.headless is True  # type: ignore[attr-defined]
        agent.start.assert_awaited_once()  # type: ignore[attr-defined]

    async def test_cached_started(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cached = SimpleNamespace(_started=True)
        monkeypatch.setattr(browser_mod, "BrowserAgent", object)
        browser_mod._agent = cached  # type: ignore[assignment]
        assert await browser_mod._get_agent() is cached  # type: ignore[comparison-overlap]

    async def test_start_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Agent:
            def __init__(self, headless: bool) -> None:
                self.headless = headless
                self.start = AsyncMock(side_effect=ImportError("no playwright"))

        monkeypatch.setattr(browser_mod, "BrowserAgent", _Agent)
        assert await browser_mod._get_agent() is None


class TestCloseAgent:
    async def test_stop_agent(self) -> None:
        stop = AsyncMock()
        browser_mod._agent = SimpleNamespace(stop=stop)  # type: ignore[assignment]
        await browser_mod._close_agent()
        assert browser_mod._agent is None
        stop.assert_awaited_once()

    async def test_no_agent(self) -> None:
        await browser_mod._close_agent()
        assert browser_mod._agent is None


class TestPageContext:
    async def test_no_browser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=None))
        async with browser_mod._page_context(url="http://example.com") as page:
            assert page is None

    async def test_navigates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        async with browser_mod._page_context(timeout=5, url="http://example.com/x") as got:
            assert got is page
        page.goto.assert_awaited_once_with("http://example.com/x", wait_until="domcontentloaded", timeout=5000)
        page.close.assert_awaited_once()

    async def test_skip_goto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        async with browser_mod._page_context(url="http://example.com", skip_goto=True) as got:
            assert got is page
        page.goto.assert_not_awaited()

    async def test_no_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        async with browser_mod._page_context() as got:
            assert got is page
        page.goto.assert_not_awaited()

    async def test_invalid_url_closes_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        with pytest.raises(ValueError, match="private IP"):
            async with browser_mod._page_context(url="http://127.0.0.1") as _:
                pass
        page.close.assert_awaited_once()

    async def test_goto_error_closes_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.goto = AsyncMock(side_effect=RuntimeError("nav fail"))
        _install_browser(monkeypatch, page)
        with pytest.raises(RuntimeError, match="nav fail"):
            async with browser_mod._page_context(url="http://example.com") as _:
                pass
        page.close.assert_awaited_once()


class TestBrowserOpen:
    async def test_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opened: list[str] = []

        def _record(url: str) -> bool:
            opened.append(url)
            return True

        monkeypatch.setattr(webbrowser, "open", _record)
        result = await browser_mod.browser_open("http://example.com")
        assert result == "Opened http://example.com in default browser"
        assert opened == ["http://example.com"]

    async def test_blocked(self) -> None:
        result = await browser_mod.browser_open("http://127.0.0.1")
        assert result.startswith("Blocked: ")


class TestBrowserNavigate:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(title="My Title", eval_result="some body text")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_navigate("http://example.com")
        assert result == "Navigated to My Title\n\nsome body text"
        page.title.assert_awaited_once()
        page.evaluate.assert_awaited_once_with("document.body.innerText")

    async def test_prepends_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_validate_url", lambda url: None)
        page = _FakePage()
        _install_browser(monkeypatch, page)
        await browser_mod.browser_navigate("www.example.com")
        page.goto.assert_awaited_once_with("https://www.example.com", wait_until="domcontentloaded", timeout=30000)

    async def test_wait_until_param_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        await browser_mod.browser_navigate("http://example.com", wait_until="load", timeout=7)
        page.goto.assert_awaited_once_with("http://example.com", wait_until="domcontentloaded", timeout=7000)

    async def test_blocked(self) -> None:
        result = await browser_mod.browser_navigate("http://127.0.0.1")
        assert result.startswith("Blocked: ")

    async def test_no_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=None))
        result = await browser_mod.browser_navigate("http://example.com")
        assert "Playwright not available" in result

    async def test_goto_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.goto = AsyncMock(side_effect=RuntimeError("goto boom"))
        _install_browser(monkeypatch, page)
        with pytest.raises(RuntimeError, match="goto boom"):
            await browser_mod.browser_navigate("http://example.com")


class TestBrowserClick:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_click("#btn", url="http://example.com", timeout=3)
        assert result == "Clicked #btn"
        page.wait_for_selector.assert_awaited_once_with("#btn", timeout=3000)
        page.click.assert_awaited_once_with("#btn")

    async def test_element_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.wait_for_selector = AsyncMock(side_effect=RuntimeError("not found"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_click("#missing") == "Click failed: not found"


class TestBrowserFill:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_fill("#in", "value", url="http://example.com", timeout=3)
        assert result == "Filled #in with 'value'"
        page.wait_for_selector.assert_awaited_once_with("#in", timeout=3000)
        page.fill.assert_awaited_once_with("#in", "value")

    async def test_truncates_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_fill("#in", "x" * 100)
        assert result == f"Filled #in with '{'x' * 50}'"

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.fill = AsyncMock(side_effect=RuntimeError("fill boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_fill("#in", "v") == "Fill failed: fill boom"


class TestBrowserType:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_type("#in", "hello", delay_ms=25, url="http://example.com")
        assert result == "Typed 'hello' into #in"
        page.type.assert_awaited_once_with("#in", "hello", delay=25)

    async def test_truncates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_type("#in", "y" * 100)
        assert result == f"Typed '{'y' * 50}' into #in"

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.type = AsyncMock(side_effect=RuntimeError("type boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_type("#in", "t") == "Type failed: type boom"


class TestBrowserSelect:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_select("#sel", "opt", url="http://example.com")
        assert result == "Selected 'opt' in #sel"
        page.select_option.assert_awaited_once_with("#sel", "opt")

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.select_option = AsyncMock(side_effect=RuntimeError("select boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_select("#sel", "opt") == "Select failed: select boom"


class TestBrowserScreenshot:
    async def test_full_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(shot=b"fake-png-bytes")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_screenshot("http://example.com")
        expected = "![Screenshot](data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode() + ")"
        assert result == expected
        page.screenshot.assert_awaited_once_with(full_page=False)

    async def test_element(self, monkeypatch: pytest.MonkeyPatch) -> None:
        el = _FakeElement(data=b"element-png")
        page = _FakePage(element=el)
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_screenshot("http://example.com", selector="#img")
        assert "data:image/png;base64," in result
        el.screenshot.assert_awaited_once()
        page.screenshot.assert_not_awaited()
        page.wait_for_selector.assert_awaited_once_with("#img", timeout=5000)

    async def test_prepends_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_validate_url", lambda url: None)
        page = _FakePage()
        _install_browser(monkeypatch, page)
        await browser_mod.browser_screenshot("www.example.com")
        page.goto.assert_awaited_once_with("https://www.example.com", wait_until="domcontentloaded", timeout=15000)

    async def test_blocked(self) -> None:
        result = await browser_mod.browser_screenshot("http://127.0.0.1")
        assert result.startswith("Blocked: ")

    async def test_no_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=None))
        result = await browser_mod.browser_screenshot("http://example.com")
        assert "Playwright not available" in result

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.screenshot = AsyncMock(side_effect=RuntimeError("shot boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_screenshot("http://example.com") == "Screenshot failed: shot boom"


class TestBrowserEvaluate:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(eval_result=12345)
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_evaluate("1 + 1", url="http://example.com")
        assert result == "12345"
        page.evaluate.assert_awaited_once_with("1 + 1")

    async def test_truncates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(eval_result="z" * 5000)
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_evaluate("x")
        assert len(result) == 4000

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.evaluate = AsyncMock(side_effect=RuntimeError("js boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_evaluate("x") == "Script execution failed: js boom"


class TestBrowserGetText:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(text="the page text")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_text(url="http://example.com")
        assert result == "the page text"
        page.wait_for_selector.assert_awaited_once_with("body", timeout=10000)
        page.inner_text.assert_awaited_once_with("body")

    async def test_custom_selector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(text="hello")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_text("#main")
        assert result == "hello"
        page.wait_for_selector.assert_awaited_once_with("#main", timeout=10000)

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.inner_text = AsyncMock(side_effect=RuntimeError("text boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_get_text() == "Get text failed: text boom"


class TestBrowserGetHtml:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(html="<div>html</div>")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_html(url="http://example.com")
        assert result == "<div>html</div>"
        page.wait_for_selector.assert_awaited_once_with("body", timeout=10000)
        page.inner_html.assert_awaited_once_with("body")

    async def test_custom_selector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(html="<p>x</p>")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_html("#main")
        assert result == "<p>x</p>"

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.inner_html = AsyncMock(side_effect=RuntimeError("html boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_get_html() == "Get HTML failed: html boom"


class TestBrowserGetAttributes:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(eval_result='{"id": "x"}')
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_attributes("#a", url="http://example.com")
        assert result == 'Attributes of #a: {"id": "x"}'
        page.goto.assert_awaited_once()
        page.wait_for_selector.assert_awaited_once_with("#a", timeout=10000)
        page.evaluate.assert_awaited_once()
        page.close.assert_awaited_once()

    async def test_no_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(eval_result="null")
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_attributes("#a")
        assert result == "Attributes of #a: null"
        page.goto.assert_not_awaited()
        page.close.assert_awaited_once()

    async def test_no_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=None))
        assert await browser_mod.browser_get_attributes("#a") == "Playwright not available"

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.wait_for_selector = AsyncMock(side_effect=RuntimeError("boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_get_attributes("#a") == "Get attributes failed: boom"
        page.close.assert_awaited_once()


class TestBrowserWait:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_wait("#x", state="hidden", url="http://example.com")
        assert result == "Selector #x is hidden"
        page.wait_for_selector.assert_awaited_once_with("#x", timeout=10000, state="hidden")

    async def test_default_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_wait("#x")
        assert result == "Selector #x is visible"
        page.wait_for_selector.assert_awaited_once_with("#x", timeout=10000, state="visible")

    async def test_no_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        await browser_mod.browser_wait("#x")
        page.goto.assert_not_awaited()
        page.close.assert_awaited_once()

    async def test_no_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=None))
        assert await browser_mod.browser_wait("#x") == "Playwright not available"

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.wait_for_selector = AsyncMock(side_effect=RuntimeError("boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_wait("#x") == "Wait failed: boom"


class TestBrowserScroll:
    async def test_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_scroll(url="http://example.com")
        assert result == "Scrolled down 500px"
        page.evaluate.assert_awaited_once_with("window.scrollBy(0, 500)")

    async def test_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_scroll(direction="up", amount=300)
        assert result == "Scrolled up 300px"
        page.evaluate.assert_awaited_once_with("window.scrollBy(0, -300)")

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.evaluate = AsyncMock(side_effect=RuntimeError("boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_scroll() == "Scroll failed: boom"


class TestBrowserGetCookies:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(cookies=[{"name": "session", "value": "abc"}, {"name": "token", "value": "v" * 60}])
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_cookies(url="http://example.com")
        assert "Cookies (2):" in result
        assert "session=abc" in result
        assert ("v" * 40) in result

    async def test_no_cookies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage(cookies=[])
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_get_cookies() == "No cookies"

    async def test_many_cookies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cookies = [{"name": f"c{i}", "value": "x"} for i in range(25)]
        page = _FakePage(cookies=cookies)
        _install_browser(monkeypatch, page)
        result = await browser_mod.browser_get_cookies()
        assert "Cookies (25):" in result

    async def test_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        page = _FakePage()
        page.context.cookies = AsyncMock(side_effect=RuntimeError("boom"))
        _install_browser(monkeypatch, page)
        assert await browser_mod.browser_get_cookies() == "Get cookies failed: boom"


class TestBrowserFillForm:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        result = await browser_mod.browser_fill_form('{"#name": "John", "#email": "j@x.io"}', timeout=5)
        assert result == "filled form"
        agent.fill_form.assert_awaited_once_with({"#name": "John", "#email": "j@x.io"}, timeout=5)

    async def test_dict_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        await browser_mod.browser_fill_form({"#name": "Jane"})  # type: ignore[arg-type]
        agent.fill_form.assert_awaited_once_with({"#name": "Jane"}, timeout=30)

    async def test_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_agent(monkeypatch)
        result = await browser_mod.browser_fill_form("{bad json")
        assert result.startswith("Invalid fields JSON: ")


class TestBrowserExtractTable:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        result = await browser_mod.browser_extract_table("#tbl")
        assert result == '{"headers": []}'
        agent.extract_table.assert_awaited_once_with("#tbl")


class TestBrowserInterceptNetwork:
    async def test_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_intercept_network("start") == "intercept started"
        agent.start_network_intercept.assert_awaited_once()

    async def test_stop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_intercept_network("stop") == "intercept stopped"
        agent.stop_network_intercept.assert_awaited_once()

    async def test_unknown_action_stops(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_intercept_network("pause") == "intercept stopped"
        agent.stop_network_intercept.assert_awaited_once()
        agent.start_network_intercept.assert_not_awaited()


class TestBrowserGetRequests:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_get_requests() == "request list"
        agent.get_intercepted_requests.assert_awaited_once()


class TestBrowserGetResponses:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_get_responses() == "response list"
        agent.get_intercepted_responses.assert_awaited_once()


class TestBrowserNewTab:
    async def test_with_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_new_tab("https://example.com") == "new tab"
        agent.new_tab.assert_awaited_once_with("https://example.com")

    async def test_blank(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        await browser_mod.browser_new_tab("")
        agent.new_tab.assert_awaited_once_with(None)


class TestBrowserCloseTab:
    async def test_close_current(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        await browser_mod.browser_close_tab()
        agent.close_tab.assert_awaited_once_with(None)

    async def test_close_specific(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        await browser_mod.browser_close_tab(2)
        agent.close_tab.assert_awaited_once_with(2)


class TestBrowserSwitchTab:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_switch_tab(1) == "switched tab"
        agent.switch_tab.assert_awaited_once_with(1)


class TestBrowserListTabs:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_list_tabs() == "tab list"
        agent.list_tabs.assert_awaited_once()


class TestBrowserDownload:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        result = await browser_mod.browser_download(timeout=7)
        assert result == "downloaded"
        agent.set_download_handler.assert_awaited_once()
        agent.get_download.assert_awaited_once_with(timeout=7)


class TestBrowserSetHeaders:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        result = await browser_mod.browser_set_headers('{"X-Api-Key": "k"}')
        assert result == "headers set"
        agent.set_extra_http_headers.assert_awaited_once_with({"X-Api-Key": "k"})

    async def test_dict_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        await browser_mod.browser_set_headers({"A": "b"})  # type: ignore[arg-type]
        agent.set_extra_http_headers.assert_awaited_once_with({"A": "b"})

    async def test_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_agent(monkeypatch)
        result = await browser_mod.browser_set_headers("{bad")
        assert result.startswith("Invalid headers JSON: ")


class TestBrowserWaitFunction:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_wait_function("() => true") == "function done"
        agent.wait_for_function.assert_awaited_once_with("() => true", timeout=30)


class TestBrowserWaitNavigation:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_wait_navigation(timeout=9) == "navigation done"
        agent.wait_for_navigation.assert_awaited_once_with(timeout=9)


class TestBrowserGetTitle:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_get_title() == "Agent Title"
        agent.get_title.assert_awaited_once()


class TestBrowserGetUrl:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_get_url() == "https://example.com/"
        agent.get_url.assert_awaited_once()


class TestBrowserSetCookies:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        result = await browser_mod.browser_set_cookies('[{"name": "a", "value": "b"}]')
        assert result == "cookies set"
        agent.set_cookies.assert_awaited_once_with([{"name": "a", "value": "b"}])

    async def test_list_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        await browser_mod.browser_set_cookies([{"name": "x"}])  # type: ignore[arg-type]
        agent.set_cookies.assert_awaited_once_with([{"name": "x"}])

    async def test_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_agent(monkeypatch)
        result = await browser_mod.browser_set_cookies("{bad")
        assert result.startswith("Invalid cookies JSON: ")


class TestBrowserClearCookies:
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = _install_agent(monkeypatch)
        assert await browser_mod.browser_clear_cookies() == "cookies cleared"
        agent.clear_cookies.assert_awaited_once()


class TestAgentUnavailable:
    async def test_all_return_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_agent", AsyncMock(return_value=None))
        assert await browser_mod.browser_fill_form("{}") == "BrowserAgent not available"
        assert await browser_mod.browser_extract_table("#t") == "BrowserAgent not available"
        assert await browser_mod.browser_intercept_network("start") == "BrowserAgent not available"
        assert await browser_mod.browser_get_requests() == "BrowserAgent not available"
        assert await browser_mod.browser_get_responses() == "BrowserAgent not available"
        assert await browser_mod.browser_new_tab() == "BrowserAgent not available"
        assert await browser_mod.browser_close_tab() == "BrowserAgent not available"
        assert await browser_mod.browser_switch_tab(0) == "BrowserAgent not available"
        assert await browser_mod.browser_list_tabs() == "BrowserAgent not available"
        assert await browser_mod.browser_download() == "BrowserAgent not available"
        assert await browser_mod.browser_set_headers("{}") == "BrowserAgent not available"
        assert await browser_mod.browser_wait_function("() => true") == "BrowserAgent not available"
        assert await browser_mod.browser_wait_navigation() == "BrowserAgent not available"
        assert await browser_mod.browser_get_title() == "BrowserAgent not available"
        assert await browser_mod.browser_get_url() == "BrowserAgent not available"
        assert await browser_mod.browser_set_cookies("[]") == "BrowserAgent not available"
        assert await browser_mod.browser_clear_cookies() == "BrowserAgent not available"


class TestPlaywrightUnavailable:
    async def test_all_return_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_mod, "_get_playwright", AsyncMock(return_value=None))
        assert await browser_mod.browser_click("#b") == "Playwright not available"
        assert await browser_mod.browser_fill("#i", "v") == "Playwright not available"
        assert await browser_mod.browser_type("#i", "t") == "Playwright not available"
        assert await browser_mod.browser_select("#s", "o") == "Playwright not available"
        assert await browser_mod.browser_evaluate("1") == "Playwright not available"
        assert await browser_mod.browser_get_text() == "Playwright not available"
        assert await browser_mod.browser_get_html() == "Playwright not available"
        assert await browser_mod.browser_scroll() == "Playwright not available"
        assert await browser_mod.browser_get_cookies() == "Playwright not available"


class TestRegisterBrowserTools:
    def test_registers_all_tools(self) -> None:
        registry = ToolRegistry()
        browser_mod.register_browser_tools(registry)
        names = [
            "browser_open",
            "browser_navigate",
            "browser_click",
            "browser_fill",
            "browser_type",
            "browser_select",
            "browser_screenshot",
            "browser_evaluate",
            "browser_get_text",
            "browser_get_html",
            "browser_get_attributes",
            "browser_wait",
            "browser_scroll",
            "browser_get_cookies",
            "browser_fill_form",
            "browser_extract_table",
            "browser_intercept_network",
            "browser_get_requests",
            "browser_get_responses",
            "browser_new_tab",
            "browser_close_tab",
            "browser_switch_tab",
            "browser_list_tabs",
            "browser_download",
            "browser_set_headers",
            "browser_wait_function",
            "browser_wait_navigation",
            "browser_get_title",
            "browser_get_url",
            "browser_set_cookies",
            "browser_clear_cookies",
        ]
        for name in names:
            assert registry.get(name) is not None
        listed = [spec.name for spec in registry.list()]
        assert len(listed) == len(names)
