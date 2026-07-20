from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from raven.core.browser_agent import BrowserAgent
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_PRIVATE_RANGES = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"]

_browser_instance = None
_browser_context = None
_lock = asyncio.Lock()


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError("URL missing hostname")
    try:
        ip = ipaddress.ip_address(host)
        for r in _PRIVATE_RANGES:
            if ip in ipaddress.ip_network(r, strict=False):
                raise ValueError(f"SSRF blocked: private IP {host}")
    except ValueError:
        if host in ("localhost", "0.0.0.0"):
            raise ValueError(f"SSRF blocked: hostname {host}") from None
        try:
            addrs = socket.getaddrinfo(host, None)
            for _family, _type, _proto, _cname, sockaddr in addrs:
                addr = str(sockaddr[0])
                try:
                    ip = ipaddress.ip_address(addr)
                    for r in _PRIVATE_RANGES:
                        if ip in ipaddress.ip_network(r, strict=False):
                            raise ValueError(f"SSRF blocked: hostname {host} resolves to private IP {addr}")
                except ValueError:
                    continue
        except (socket.gaierror, OSError):
            logger.warning("SSRF guard: DNS resolution failed for {}", host)


async def _get_playwright() -> Any | None:
    global _browser_instance, _browser_context
    async with _lock:
        if _browser_context is not None:
            return _browser_context
        try:
            from playwright.async_api import async_playwright
            p = await async_playwright().start()
            _browser_instance = p
            _browser_context = await p.chromium.launch(headless=True)
            return _browser_context
        except ImportError:
            return None


async def _close_playwright() -> None:
    global _browser_instance, _browser_context
    async with _lock:
        if _browser_instance:
            try:
                await _browser_instance.stop()
            except Exception as exc:
                logger.debug("Failed to stop browser instance: {}", exc)
            _browser_instance = None
            _browser_context = None


_agent: BrowserAgent | None = None
_agent_lock = asyncio.Lock()


async def _get_agent() -> BrowserAgent | None:
    global _agent
    async with _agent_lock:
        if _agent is not None and _agent._started:
            return _agent
        try:
            a = BrowserAgent(headless=True)
            await a.start()
            _agent = a
            return _agent
        except ImportError:
            return None


async def _close_agent() -> None:
    global _agent
    async with _agent_lock:
        if _agent:
            await _agent.stop()
            _agent = None


async def browser_open(url: str) -> str:
    import webbrowser
    await asyncio.to_thread(webbrowser.open, url)
    return f"Opened {url} in default browser"


async def browser_navigate(url: str, wait_until: str = "domcontentloaded", timeout: int = 30) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available. Install: pip install playwright && playwright install chromium"
    try:
        _validate_url(url)
    except ValueError as e:
        return f"Blocked: {e}"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = await browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
        title = await page.title()
        text = await page.evaluate("document.body.innerText")
        return f"Navigated to {title}\n\n{text[:6000]}"
    finally:
        await page.close()


async def browser_click(selector: str, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        await page.click(selector)
        await asyncio.sleep(1)
        return f"Clicked {selector}"
    except Exception as e:
        return f"Click failed: {e}"
    finally:
        await page.close()


async def browser_fill(selector: str, value: str, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        await page.fill(selector, value)
        return f"Filled {selector} with '{value[:50]}'"
    except Exception as e:
        return f"Fill failed: {e}"
    finally:
        await page.close()


async def browser_type(selector: str, text: str, delay_ms: int = 50, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        await page.type(selector, text, delay=delay_ms)
        return f"Typed '{text[:50]}' into {selector}"
    except Exception as e:
        return f"Type failed: {e}"
    finally:
        await page.close()


async def browser_select(selector: str, value: str, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        await page.select_option(selector, value)
        return f"Selected '{value}' in {selector}"
    except Exception as e:
        return f"Select failed: {e}"
    finally:
        await page.close()


async def browser_screenshot(url: str, selector: str = "", timeout: int = 15) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available. Install: pip install playwright && playwright install chromium"
    try:
        _validate_url(url)
    except ValueError as e:
        return f"Blocked: {e}"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = await browser.new_page(viewport={"width": 1280, "height": 720})
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        await asyncio.sleep(2)
        if selector:
            el = await page.wait_for_selector(selector, timeout=5000)
            screenshot_bytes = await el.screenshot()
        else:
            screenshot_bytes = await page.screenshot(full_page=False)
        b64 = base64.b64encode(screenshot_bytes).decode()
        return f"![Screenshot](data:image/png;base64,{b64})"
    except Exception as e:
        return f"Screenshot failed: {e}"
    finally:
        await page.close()


async def browser_evaluate(script: str, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        result = await page.evaluate(script)
        return str(result)[:4000]
    except Exception as e:
        return f"Script execution failed: {e}"
    finally:
        await page.close()


async def browser_get_text(selector: str = "body", url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        text = str(await page.inner_text(selector))
        return text[:6000]
    except Exception as e:
        return f"Get text failed: {e}"
    finally:
        await page.close()


async def browser_get_html(selector: str = "body", url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        html = str(await page.inner_html(selector))
        return html[:6000]
    except Exception as e:
        return f"Get HTML failed: {e}"
    finally:
        await page.close()


async def browser_get_attributes(selector: str, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        attrs = await page.evaluate(f"(function() {{ const el = document.querySelector('{selector}'); if (!el) return null; const a = {{}}; for (const attr of el.attributes) {{ a[attr.name] = attr.value; }} return JSON.stringify(a); }})()")
        return f"Attributes of {selector}: {attrs}"
    except Exception as e:
        return f"Get attributes failed: {e}"
    finally:
        await page.close()


async def browser_wait(selector: str, timeout: int = 10, state: str = "visible", url: str = "") -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_selector(selector, timeout=timeout * 1000)
        return f"Selector {selector} is {state}"
    except Exception as e:
        return f"Wait failed: {e}"
    finally:
        await page.close()


async def browser_scroll(direction: str = "down", amount: int = 500, url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        sign = -1 if direction == "up" else 1
        await page.evaluate(f"window.scrollBy(0, {sign * amount})")
        await asyncio.sleep(0.5)
        return f"Scrolled {direction} {amount}px"
    except Exception as e:
        return f"Scroll failed: {e}"
    finally:
        await page.close()


async def browser_get_cookies(url: str = "", timeout: int = 10) -> str:
    browser = await _get_playwright()
    if not browser:
        return "Playwright not available"
    page = await browser.new_page()
    try:
        if url:
            _validate_url(url)
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        cookies = await page.context.cookies()
        if not cookies:
            return "No cookies"
        summary = "\n".join(f"  {c['name']}={c['value'][:40]}" for c in cookies[:20])
        return f"Cookies ({len(cookies)}):\n{summary}"
    except Exception as e:
        return f"Get cookies failed: {e}"
    finally:
        await page.close()


async def browser_fill_form(fields: str, timeout: int = 30) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    try:
        fd = json.loads(fields) if isinstance(fields, str) else fields
    except Exception as e:
        return f"Invalid fields JSON: {e}"
    return await agent.fill_form(fd, timeout=timeout)


async def browser_extract_table(selector: str) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.extract_table(selector)


async def browser_intercept_network(action: str = "start") -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    if action == "start":
        return await agent.start_network_intercept()
    return await agent.stop_network_intercept()


async def browser_get_requests() -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.get_intercepted_requests()


async def browser_get_responses() -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.get_intercepted_responses()


async def browser_new_tab(url: str = "") -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.new_tab(url or None)


async def browser_close_tab(index: int = -1) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.close_tab(index if index >= 0 else None)


async def browser_switch_tab(index: int) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.switch_tab(index)


async def browser_list_tabs() -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.list_tabs()


async def browser_download(timeout: int = 30) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    await agent.set_download_handler()
    return await agent.get_download(timeout=timeout)


async def browser_set_headers(headers: str) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    try:
        hd = json.loads(headers) if isinstance(headers, str) else headers
    except Exception as e:
        return f"Invalid headers JSON: {e}"
    return await agent.set_extra_http_headers(hd)


async def browser_wait_function(fn: str, timeout: int = 30) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.wait_for_function(fn, timeout=timeout)


async def browser_wait_navigation(timeout: int = 30) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.wait_for_navigation(timeout=timeout)


async def browser_get_title() -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.get_title()


async def browser_get_url() -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.get_url()


async def browser_set_cookies(cookies: str) -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    try:
        ck = json.loads(cookies) if isinstance(cookies, str) else cookies
    except Exception as e:
        return f"Invalid cookies JSON: {e}"
    return await agent.set_cookies(ck)


async def browser_clear_cookies() -> str:
    agent = await _get_agent()
    if not agent:
        return "BrowserAgent not available"
    return await agent.clear_cookies()


def register_browser_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(name="browser_open", description="Open a URL in the default system browser", parameters={"url": {"type": "string", "description": "URL to open", "required": True}}, handler=browser_open, category="web"))
    registry.register(ToolSpec(name="browser_navigate", description="Navigate to a URL and return page text content", parameters={"url": {"type": "string", "description": "URL to visit", "required": True}, "wait_until": {"type": "string", "description": "Wait condition: domcontentloaded, load, networkidle", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_navigate, category="web", timeout=60))
    registry.register(ToolSpec(name="browser_click", description="Click an element on the page using CSS selector", parameters={"selector": {"type": "string", "description": "CSS selector to click", "required": True}, "url": {"type": "string", "description": "Optional URL to navigate to first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_click, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_fill", description="Fill an input field with text (clears existing content)", parameters={"selector": {"type": "string", "description": "CSS selector of input field", "required": True}, "value": {"type": "string", "description": "Text to fill", "required": True}, "url": {"type": "string", "description": "Optional URL to navigate to first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_fill, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_type", description="Type text into an element with simulated keystrokes", parameters={"selector": {"type": "string", "description": "CSS selector", "required": True}, "text": {"type": "string", "description": "Text to type", "required": True}, "delay_ms": {"type": "integer", "description": "Delay between keystrokes in ms", "required": False}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_type, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_select", description="Select an option from a <select> element", parameters={"selector": {"type": "string", "description": "CSS selector of select element", "required": True}, "value": {"type": "string", "description": "Option value to select", "required": True}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_select, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_screenshot", description="Take a screenshot of a page or element as base64 image", parameters={"url": {"type": "string", "description": "URL to capture", "required": True}, "selector": {"type": "string", "description": "Optional CSS selector to screenshot a specific element", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_screenshot, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_evaluate", description="Execute JavaScript in the browser page and return result", parameters={"script": {"type": "string", "description": "JavaScript code to execute", "required": True}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_evaluate, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_get_text", description="Get inner text of an element (default: entire page)", parameters={"selector": {"type": "string", "description": "CSS selector (default: body)", "required": False}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_get_text, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_get_html", description="Get inner HTML of an element (default: entire page)", parameters={"selector": {"type": "string", "description": "CSS selector (default: body)", "required": False}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_get_html, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_get_attributes", description="Get all attributes of an element", parameters={"selector": {"type": "string", "description": "CSS selector", "required": True}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_get_attributes, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_wait", description="Wait for an element to appear on the page", parameters={"selector": {"type": "string", "description": "CSS selector to wait for", "required": True}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}, "state": {"type": "string", "description": "Expected state: visible, hidden, attached", "required": False}, "url": {"type": "string", "description": "Optional URL first", "required": False}}, handler=browser_wait, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_scroll", description="Scroll the page in a direction", parameters={"direction": {"type": "string", "description": "Direction: down or up", "required": False}, "amount": {"type": "integer", "description": "Pixels to scroll", "required": False}, "url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_scroll, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_get_cookies", description="Get cookies for the current page", parameters={"url": {"type": "string", "description": "Optional URL first", "required": False}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_get_cookies, category="web", timeout=30))
    # Enhanced BrowserAgent tools
    registry.register(ToolSpec(name="browser_fill_form", description="Fill multiple form fields at once using a JSON dict of {selector: value}", parameters={"fields": {"type": "string", "description": "JSON object mapping CSS selectors to values, e.g. {\"#name\": \"John\", \"#email\": \"john@test.com\"}", "required": True}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_fill_form, category="web", timeout=60))
    registry.register(ToolSpec(name="browser_extract_table", description="Extract an HTML table as structured JSON (headers + row data)", parameters={"selector": {"type": "string", "description": "CSS selector of the table element", "required": True}}, handler=browser_extract_table, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_intercept_network", description="Start or stop network request/response interception", parameters={"action": {"type": "string", "description": "'start' to begin capturing, 'stop' to end and report", "required": False}}, handler=browser_intercept_network, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_get_requests", description="Get captured network requests from active intercept session", parameters={}, handler=browser_get_requests, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_get_responses", description="Get captured network responses from active intercept session", parameters={}, handler=browser_get_responses, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_new_tab", description="Open a new browser tab (optionally navigate to URL)", parameters={"url": {"type": "string", "description": "URL to navigate to in the new tab (optional)", "required": False}}, handler=browser_new_tab, category="web", timeout=30))
    registry.register(ToolSpec(name="browser_close_tab", description="Close a browser tab by index (default: current tab)", parameters={"index": {"type": "integer", "description": "Tab index to close (-1 for current)", "required": False}}, handler=browser_close_tab, category="web", timeout=15))
    registry.register(ToolSpec(name="browser_switch_tab", description="Switch to a different browser tab by index", parameters={"index": {"type": "integer", "description": "Tab index to switch to", "required": True}}, handler=browser_switch_tab, category="web", timeout=15))
    registry.register(ToolSpec(name="browser_list_tabs", description="List all open browser tabs with titles and URLs", parameters={}, handler=browser_list_tabs, category="web", timeout=15))
    registry.register(ToolSpec(name="browser_download", description="Wait for and capture a downloaded file as base64", parameters={"timeout": {"type": "integer", "description": "Max wait time in seconds", "required": False}}, handler=browser_download, category="web", timeout=60))
    registry.register(ToolSpec(name="browser_set_headers", description="Set extra HTTP headers for all requests from this page", parameters={"headers": {"type": "string", "description": "JSON object of header key-value pairs", "required": True}}, handler=browser_set_headers, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_wait_function", description="Wait until a JavaScript function returns a truthy value", parameters={"fn": {"type": "string", "description": "JavaScript function body to evaluate (e.g. '() => document.querySelectorAll(\".item\").length > 5')", "required": True}, "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_wait_function, category="web", timeout=60))
    registry.register(ToolSpec(name="browser_wait_navigation", description="Wait for the page to finish loading (network idle)", parameters={"timeout": {"type": "integer", "description": "Timeout in seconds", "required": False}}, handler=browser_wait_navigation, category="web", timeout=60))
    registry.register(ToolSpec(name="browser_get_title", description="Get the current page title", parameters={}, handler=browser_get_title, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_get_url", description="Get the current page URL", parameters={}, handler=browser_get_url, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_set_cookies", description="Set cookies for the current browser context from JSON array", parameters={"cookies": {"type": "string", "description": "JSON array of cookie objects: [{\"name\":\"x\",\"value\":\"y\",\"url\":\"...\"}]", "required": True}}, handler=browser_set_cookies, category="web", timeout=10))
    registry.register(ToolSpec(name="browser_clear_cookies", description="Clear all cookies for the current browser context", parameters={}, handler=browser_clear_cookies, category="web", timeout=10))
