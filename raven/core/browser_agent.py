from __future__ import annotations

import asyncio
import base64
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from loguru import logger

_PRIVATE_RANGES = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"]


def validate_url(url: str) -> None:
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
                addr = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(addr)
                    for r in _PRIVATE_RANGES:
                        if ip in ipaddress.ip_network(r, strict=False):
                            raise ValueError(f"SSRF blocked: hostname {host} resolves to private IP {addr}")
                except ValueError:
                    continue
        except (socket.gaierror, OSError):
            logger.warning("SSRF guard: DNS resolution failed for {}", host)


@dataclass
class InterceptedRequest:
    url: str
    method: str
    headers: dict[str, str]
    body: str | None
    timestamp: float


@dataclass
class InterceptedResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: str | None
    timestamp: float


class BrowserAgent:
    def __init__(
        self,
        headless: bool = True,
        viewport: dict[str, int] | None = None,
        user_agent: str | None = None,
        locale: str | None = None,
        timeout: int = 30,
    ) -> None:
        self._headless = headless
        self._viewport = viewport or {"width": 1280, "height": 720}
        self._user_agent = user_agent
        self._locale = locale
        self._timeout = timeout
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._tabs: list[Any] = []
        self._tab_index = 0
        self._intercepted_requests: list[InterceptedRequest] = []
        self._intercepted_responses: list[InterceptedResponse] = []
        self._intercept_active = False
        self._started = False
        self._download_future: asyncio.Future[bytes] | None = None

    async def start(self) -> None:
        if self._started:
            return
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            context_options: dict[str, Any] = {
                "viewport": self._viewport,
            }
            if self._user_agent:
                context_options["user_agent"] = self._user_agent
            if self._locale:
                context_options["locale"] = self._locale
            self._context = await self._browser.new_context(**context_options)
            self._page = await self._context.new_page()
            self._tabs = [self._page]
            self._tab_index = 0
            self._started = True
            logger.debug("[browser_agent] started")
        except ImportError:
            logger.warning("[browser_agent] playwright not installed")
            raise
        except Exception as e:
            logger.error("[browser_agent] start failed: {}", e)
            await self.stop()
            raise

    async def stop(self) -> None:
        self._started = False
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.debug("[browser_agent] stop error: {}", e)
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._tabs = []
            self._tab_index = 0
            self._intercepted_requests.clear()
            self._intercepted_responses.clear()
            self._intercept_active = False
            logger.debug("[browser_agent] stopped")

    @property
    def page(self) -> Any:
        if not self._page:
            raise RuntimeError("BrowserAgent not started")
        return self._page

    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout: int | None = None) -> str:
        validate_url(url)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        t = (timeout or self._timeout) * 1000
        await self.page.goto(url, wait_until=wait_until, timeout=t)
        title = await self.page.title()
        text = await self.page.evaluate("document.body.innerText")
        return f"Navigated to {title}\n\n{text[:6000]}"

    async def click(self, selector: str, timeout: int | None = None) -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_selector(selector, timeout=t)
        await self.page.click(selector)
        await asyncio.sleep(0.5)
        return f"Clicked {selector}"

    async def fill(self, selector: str, value: str, timeout: int | None = None) -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_selector(selector, timeout=t)
        await self.page.fill(selector, value)
        return f"Filled {selector} with '{value[:50]}'"

    async def type_text(self, selector: str, text: str, delay_ms: int = 50, timeout: int | None = None) -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_selector(selector, timeout=t)
        await self.page.type(selector, text, delay=delay_ms)
        return f"Typed '{text[:50]}' into {selector}"

    async def fill_form(self, fields: dict[str, str], timeout: int | None = None) -> str:
        filled = []
        for selector, value in fields.items():
            try:
                t = (timeout or self._timeout) * 1000
                await self.page.wait_for_selector(selector, timeout=t)
                await self.page.fill(selector, value)
                filled.append(selector)
            except Exception as e:
                logger.debug("[browser_agent] fill_form failed for '{}': {}", selector, e)
        if not filled:
            return "No fields could be filled"
        return f"Filled {len(filled)} field(s): {', '.join(filled)}"

    async def extract_table(self, selector: str) -> str:
        result = await self.page.evaluate(f"""() => {{
            const table = document.querySelector('{selector}');
            if (!table) return JSON.stringify({{error: 'Table not found'}});
            const rows = table.querySelectorAll('tr');
            const headers = [];
            const data = [];
            const headerRow = rows[0];
            if (headerRow) {{
                headerRow.querySelectorAll('th, td').forEach(th => headers.push(th.innerText.trim()));
            }}
            for (let i = 1; i < rows.length; i++) {{
                const row = {{}};
                const cells = rows[i].querySelectorAll('td');
                cells.forEach((cell, j) => {{
                    row[headers[j] || `col${{j}}`] = cell.innerText.trim();
                }});
                data.push(row);
            }}
            return JSON.stringify({{headers, data, rowCount: data.length}});
        }}""")
        return result[:10000]  # type: ignore[no-any-return]

    async def select_option(self, selector: str, value: str, timeout: int | None = None) -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_selector(selector, timeout=t)
        await self.page.select_option(selector, value)
        return f"Selected '{value}' in {selector}"

    async def screenshot(self, selector: str | None = None, full_page: bool = False) -> str:
        if selector:
            el = await self.page.wait_for_selector(selector, timeout=5000)
            screenshot_bytes = await el.screenshot()
        else:
            screenshot_bytes = await self.page.screenshot(full_page=full_page)
        b64 = base64.b64encode(screenshot_bytes).decode()
        return f"![Screenshot](data:image/png;base64,{b64})"

    async def screenshot_bytes(self, selector: str | None = None, full_page: bool = False) -> bytes:
        if selector:
            el = await self.page.wait_for_selector(selector, timeout=5000)
            return await el.screenshot()  # type: ignore[no-any-return]
        return await self.page.screenshot(full_page=full_page)  # type: ignore[no-any-return]

    async def evaluate(self, script: str) -> str:
        result = await self.page.evaluate(script)
        return str(result)[:4000]

    async def get_text(self, selector: str = "body") -> str:
        await self.page.wait_for_selector(selector, timeout=self._timeout * 1000)
        text = await self.page.inner_text(selector)
        return text[:6000]  # type: ignore[no-any-return]

    async def get_html(self, selector: str = "body") -> str:
        await self.page.wait_for_selector(selector, timeout=self._timeout * 1000)
        page_html = await self.page.inner_html(selector)
        return page_html[:6000]  # type: ignore[no-any-return]

    async def extract_content(self, url: str | None = None) -> str:
        if url:
            await self.navigate(url)
        result = await self.page.evaluate("""(() => {
            const article = document.querySelector('article');
            if (article) return article.innerText;
            const main = document.querySelector('main');
            if (main) return main.innerText;
            const content = document.querySelector('[role="main"]');
            if (content) return content.innerText;
            const body = document.body;
            const clone = body.cloneNode(true);
            const removals = clone.querySelectorAll('nav, header, footer, aside, script, style, .sidebar, .nav, .footer, .header, .ad, .advertisement, .menu, .social-share, .comments, noscript');
            removals.forEach(el => el.remove());
            return clone.innerText;
        })()""")
        cleaned = re.sub(r'\s+', ' ', str(result or "")).strip()
        return cleaned[:10000]

    async def get_attributes(self, selector: str) -> str:
        await self.page.wait_for_selector(selector, timeout=self._timeout * 1000)
        attrs = await self.page.evaluate(f"""(function() {{
            const el = document.querySelector('{selector}');
            if (!el) return null;
            const a = {{}};
            for (const attr of el.attributes) {{ a[attr.name] = attr.value; }}
            return JSON.stringify(a);
        }})()""")
        return f"Attributes of {selector}: {attrs}"

    async def wait_for_selector(self, selector: str, timeout: int | None = None, state: str = "visible") -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_selector(selector, timeout=t, state=state)
        return f"Selector {selector} is {state}"

    async def wait_for_function(self, fn: str, timeout: int | None = None) -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_function(fn, timeout=t)
        return "Function returned truthy"

    async def wait_for_navigation(self, timeout: int | None = None) -> str:
        t = (timeout or self._timeout) * 1000
        await self.page.wait_for_load_state("networkidle", timeout=t)
        title = await self.page.title()
        return f"Navigation complete — {title}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        sign = -1 if direction == "up" else 1
        await self.page.evaluate(f"window.scrollBy(0, {sign * amount})")
        await asyncio.sleep(0.5)
        return f"Scrolled {direction} {amount}px"

    async def get_cookies(self, url: str | None = None) -> str:
        cookies = await self.page.context.cookies(url) if url else await self.page.context.cookies()
        if not cookies:
            return "No cookies"
        summary = "\n".join(f"  {c['name']}={c['value'][:40]}" for c in cookies[:20])
        return f"Cookies ({len(cookies)}):\n{summary}"

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> str:
        await self.page.context.add_cookies(cookies)
        return f"Set {len(cookies)} cookie(s)"

    async def clear_cookies(self) -> str:
        await self.page.context.clear_cookies()
        return "Cookies cleared"

    async def start_network_intercept(self, patterns: list[str] | None = None) -> str:
        if self._intercept_active:
            return "Network intercept already active"
        self._intercepted_requests.clear()
        self._intercepted_responses.clear()

        async def on_request(request: Any) -> None:
            body = None
            try:
                body = str(await request.body())
            except Exception as exc:
                logger.debug("Failed to read request body: {}", exc)
            self._intercepted_requests.append(InterceptedRequest(
                url=request.url,
                method=request.method,
                headers=dict(request.headers),
                body=body,
                timestamp=__import__("time").time(),
            ))

        async def on_response(response: Any) -> None:
            body = None
            try:
                body = str(await response.body())
            except Exception as exc:
                logger.debug("Failed to read response body: {}", exc)
            self._intercepted_responses.append(InterceptedResponse(
                url=response.url,
                status=response.status,
                headers=dict(response.headers),
                body=body,
                timestamp=__import__("time").time(),
            ))

        self._page.on("request", on_request)
        self._page.on("response", on_response)
        self._intercept_active = True
        return "Network intercept started"

    async def stop_network_intercept(self) -> str:
        if not self._intercept_active:
            return "Network intercept not active"
        req_count = len(self._intercepted_requests)
        resp_count = len(self._intercepted_responses)
        self._intercept_active = False
        return f"Network intercept stopped. Captured {req_count} requests, {resp_count} responses."

    async def get_intercepted_requests(self) -> str:
        import json
        if not self._intercepted_requests:
            return "No intercepted requests"
        data = [
            {"url": r.url, "method": r.method, "headers": r.headers, "body_len": len(r.body or "")}
            for r in self._intercepted_requests[-50:]
        ]
        return json.dumps(data, indent=2)[:10000]

    async def get_intercepted_responses(self) -> str:
        import json
        if not self._intercepted_responses:
            return "No intercepted responses"
        data = [
            {"url": r.url, "status": r.status, "headers": r.headers, "body_len": len(r.body or "")}
            for r in self._intercepted_responses[-50:]
        ]
        return json.dumps(data, indent=2)[:10000]

    async def new_tab(self, url: str | None = None) -> str:
        page = await self._context.new_page()
        self._tabs.append(page)
        self._page = page
        self._tab_index = len(self._tabs) - 1
        if url:
            validate_url(url)
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout * 1000)
            return f"New tab {self._tab_index}: {url}"
        return f"New tab {self._tab_index} (blank)"

    async def close_tab(self, index: int | None = None) -> str:
        idx = index if index is not None else self._tab_index
        if idx < 0 or idx >= len(self._tabs):
            return f"Invalid tab index {idx}"
        page = self._tabs[idx]
        await page.close()
        self._tabs.pop(idx)
        if idx <= self._tab_index and self._tab_index > 0:
            self._tab_index -= 1
        if self._tab_index >= len(self._tabs):
            self._tab_index = len(self._tabs) - 1
        if self._tabs:
            self._page = self._tabs[self._tab_index]
        return f"Closed tab {idx}"

    async def switch_tab(self, index: int) -> str:
        if index < 0 or index >= len(self._tabs):
            return f"Invalid tab index {index}. Tabs: {len(self._tabs)}"
        self._page = self._tabs[index]
        self._tab_index = index
        title = await self.page.title()
        return f"Switched to tab {index}: {title}"

    async def list_tabs(self) -> str:
        lines = []
        for i, p in enumerate(self._tabs):
            try:
                title = await p.title()
                url = p.url
                marker = " <-- active" if i == self._tab_index else ""
                lines.append(f"  [{i}] {title} ({url}){marker}")
            except Exception:
                logger.debug("Failed to get tab {} info, marking as closed", i)
                lines.append(f"  [{i}] <closed>")
        return f"Tabs ({len(self._tabs)}):\n" + "\n".join(lines)

    async def set_download_handler(self) -> str:
        async def on_download(download: Any) -> None:
            if self._download_future and not self._download_future.done():
                try:
                    data = await download.read()
                    self._download_future.set_result(data)
                except Exception as e:
                    self._download_future.set_exception(e)

        self._page.on("download", on_download)
        return "Download handler set"

    async def get_download(self, timeout: int = 30) -> str:
        self._download_future = asyncio.get_event_loop().create_future()
        try:
            data = await asyncio.wait_for(self._download_future, timeout=timeout)
            b64 = base64.b64encode(data).decode()
            return f"Downloaded file ({len(data)} bytes): data:application/octet-stream;base64,{b64[:5000]}"
        except TimeoutError:
            return "Download timed out"
        finally:
            self._download_future = None

    async def get_title(self) -> str:
        return await self.page.title()  # type: ignore[no-any-return]

    async def get_url(self) -> str:
        return self.page.url  # type: ignore[no-any-return]

    async def set_extra_http_headers(self, headers: dict[str, str]) -> str:
        await self.page.set_extra_http_headers(headers)
        return f"Headers set: {headers}"

    async def __aenter__(self) -> BrowserAgent:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()
