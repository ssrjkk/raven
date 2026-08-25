from __future__ import annotations

import asyncio
import base64
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.browser_agent import BrowserAgent

_agent: BrowserAgent | None = None


async def _get_agent() -> BrowserAgent:
    global _agent
    if _agent is not None and _agent._started:
        return _agent
    try:
        a = BrowserAgent(headless=True)
        await a.start()
        _agent = a
        return _agent
    except ImportError:
        raise HTTPException(503, "Playwright not available") from None


async def _stop_agent() -> None:
    global _agent
    if _agent:
        await _agent.stop()
        _agent = None


async def _compute_diff(img_a: bytes, img_b: bytes) -> float:
    try:
        from io import BytesIO

        from PIL import Image

        def _diff() -> float:
            a = Image.open(BytesIO(img_a)).convert("RGB")
            b = Image.open(BytesIO(img_b)).convert("RGB")
            if a.size != b.size:
                b = b.resize(a.size)
            diff = 0
            total = a.size[0] * a.size[1]
            for x in range(a.size[0]):
                for y in range(a.size[1]):
                    pa = a.getpixel((x, y))
                    pb = b.getpixel((x, y))
                    if isinstance(pa, (tuple, list)) and isinstance(pb, (tuple, list)):
                        diff += abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2])
            max_diff = total * 3 * 255
            return round((diff / max_diff) * 100, 2)

        return await asyncio.to_thread(_diff)
    except ImportError:
        return -1.0
    except Exception as e:
        logger.debug("Image diff comparison failed: {}", e)
        return -1.0


def _http_err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


class NavigateRequest(BaseModel):
    url: str
    wait_until: str = "domcontentloaded"
    timeout: int = 30


class VisualDiffRequest(BaseModel):
    url_a: str
    url_b: str
    full_page: bool = False


class ExtractContentRequest(BaseModel):
    url: str | None = None


class ClickRequest(BaseModel):
    selector: str
    timeout: int = 10


class FillRequest(BaseModel):
    selector: str
    value: str
    timeout: int = 10


class TypeRequest(BaseModel):
    selector: str
    text: str
    delay_ms: int = 50
    timeout: int = 10


class FillFormRequest(BaseModel):
    fields: dict[str, str]
    timeout: int = 10


class SelectOptionRequest(BaseModel):
    selector: str
    value: str
    timeout: int = 10


class ScreenshotRequest(BaseModel):
    selector: str | None = None
    full_page: bool = False


class EvaluateRequest(BaseModel):
    script: str


class SelectorRequest(BaseModel):
    selector: str = "body"
    timeout: int = 10


class WaitSelectorRequest(BaseModel):
    selector: str
    timeout: int = 10
    state: str = "visible"


class ScrollRequest(BaseModel):
    direction: str = "down"
    amount: int = 500


class SetCookiesRequest(BaseModel):
    cookies: list[dict[str, Any]]


class SetHeadersRequest(BaseModel):
    headers: dict[str, str]


class NewTabRequest(BaseModel):
    url: str | None = None


class SwitchTabRequest(BaseModel):
    index: int


class CloseTabRequest(BaseModel):
    index: int | None = None


class DownloadRequest(BaseModel):
    timeout: int = 30


class WaitFunctionRequest(BaseModel):
    fn: str
    timeout: int = 30


class WaitNavigationRequest(BaseModel):
    timeout: int = 30


class InterceptRequest(BaseModel):
    action: str = "start"


def create_browser_router() -> APIRouter:
    router = APIRouter(prefix="/api/browser", tags=["browser"])

    async def _call(method: str, *args: Any, **kw: Any) -> Any:
        agent = await _get_agent()
        fn = getattr(agent, method, None)
        if fn is None:
            raise _http_err(400, f"Unknown method: {method}")
        return await fn(*args, **kw)

    @router.post("/start")
    async def api_browser_start():
        await _get_agent()
        return {"status": "started"}

    @router.post("/stop")
    async def api_browser_stop():
        await _stop_agent()
        return {"status": "stopped"}

    @router.get("/status")
    async def api_browser_status():
        global _agent
        if _agent and _agent._started:
            try:
                return {"started": True, "title": await _agent.get_title(), "url": _agent.page.url}
            except Exception as e:
                logger.debug("Failed to get browser title/URL for status: {}", e)
                return {"started": True}
        return {"started": False}

    @router.post("/navigate")
    async def api_browser_navigate(req: NavigateRequest):
        try:
            text = await _call("navigate", req.url, wait_until=req.wait_until, timeout=req.timeout)
            agent = await _get_agent()
            return {"text": text, "title": await agent.get_title(), "url": agent.page.url}
        except ValueError as e:
            raise _http_err(400, str(e)) from e
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("[browser] navigate failed: {}", e)
            raise _http_err(500, str(e)) from e

    @router.post("/click")
    async def api_browser_click(req: ClickRequest):
        try:
            result = await _call("click", req.selector, timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/fill")
    async def api_browser_fill(req: FillRequest):
        try:
            result = await _call("fill", req.selector, req.value, timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/type")
    async def api_browser_type(req: TypeRequest):
        try:
            result = await _call("type_text", req.selector, req.text, delay_ms=req.delay_ms, timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/fill-form")
    async def api_browser_fill_form(req: FillFormRequest):
        try:
            result = await _call("fill_form", req.fields, timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/select")
    async def api_browser_select(req: SelectOptionRequest):
        try:
            result = await _call("select_option", req.selector, req.value, timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/screenshot")
    async def api_browser_screenshot(req: ScreenshotRequest):
        try:
            result = await _call("screenshot", selector=req.selector, full_page=req.full_page)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/evaluate")
    async def api_browser_evaluate(req: EvaluateRequest):
        try:
            result = await _call("evaluate", req.script)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/text")
    async def api_browser_get_text(req: SelectorRequest):
        try:
            text = await _call("get_text", req.selector)
            return {"text": text}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/html")
    async def api_browser_get_html(req: SelectorRequest):
        try:
            html = await _call("get_html", req.selector)
            return {"html": html}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/wait-selector")
    async def api_browser_wait_selector(req: WaitSelectorRequest):
        try:
            result = await _call("wait_for_selector", req.selector, timeout=req.timeout, state=req.state)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/wait-function")
    async def api_browser_wait_function(req: WaitFunctionRequest):
        try:
            result = await _call("wait_for_function", req.fn, timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/wait-navigation")
    async def api_browser_wait_navigation(req: WaitNavigationRequest):
        try:
            result = await _call("wait_for_navigation", timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/scroll")
    async def api_browser_scroll(req: ScrollRequest):
        try:
            result = await _call("scroll", req.direction, req.amount)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.get("/cookies")
    async def api_browser_get_cookies():
        try:
            result = await _call("get_cookies")
            return {"cookies": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/cookies")
    async def api_browser_set_cookies(req: SetCookiesRequest):
        try:
            result = await _call("set_cookies", req.cookies)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.delete("/cookies")
    async def api_browser_clear_cookies():
        try:
            result = await _call("clear_cookies")
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/intercept")
    async def api_browser_intercept(req: InterceptRequest):
        try:
            if req.action == "start":
                result = await _call("start_network_intercept")
            else:
                result = await _call("stop_network_intercept")
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.get("/requests")
    async def api_browser_get_requests():
        try:
            result = await _call("get_intercepted_requests")
            return {"requests": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.get("/responses")
    async def api_browser_get_responses():
        try:
            result = await _call("get_intercepted_responses")
            return {"responses": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/tabs")
    async def api_browser_new_tab(req: NewTabRequest):
        try:
            result = await _call("new_tab", req.url)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.get("/tabs")
    async def api_browser_list_tabs():
        try:
            result = await _call("list_tabs")
            return {"tabs": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/tabs/switch")
    async def api_browser_switch_tab(req: SwitchTabRequest):
        try:
            result = await _call("switch_tab", req.index)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/tabs/close")
    async def api_browser_close_tab(req: CloseTabRequest):
        try:
            result = await _call("close_tab", index=req.index)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/extract-table")
    async def api_browser_extract_table(req: SelectorRequest):
        try:
            result = await _call("extract_table", req.selector)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/headers")
    async def api_browser_set_headers(req: SetHeadersRequest):
        try:
            result = await _call("set_extra_http_headers", req.headers)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/download")
    async def api_browser_download(req: DownloadRequest):
        try:
            await _call("set_download_handler")
            result = await _call("get_download", timeout=req.timeout)
            return {"result": result}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.get("/title")
    async def api_browser_get_title():
        try:
            title = await _call("get_title")
            return {"title": title}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.get("/url")
    async def api_browser_get_url():
        try:
            agent = await _get_agent()
            return {"url": agent.page.url}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/extract")
    async def api_browser_extract(req: ExtractContentRequest):
        try:
            agent = await _get_agent()
            content = await agent.extract_content(url=req.url)
            return {"content": content, "url": req.url or agent.page.url}
        except Exception as e:
            raise _http_err(500, str(e)) from e

    @router.post("/visual-diff")
    async def api_browser_visual_diff(req: VisualDiffRequest):
        try:
            agent = await _get_agent()
            img_a = await agent.screenshot_bytes(full_page=req.full_page)
            agent2 = await _get_agent()
            await agent2.navigate(req.url_b)
            img_b = await agent2.screenshot_bytes(full_page=req.full_page)
            diff_pct = await _compute_diff(img_a, img_b)
            return {
                "diff_percent": diff_pct,
                "url_a": req.url_a,
                "url_b": req.url_b,
                "screenshot_a": f"data:image/png;base64,{base64.b64encode(img_a).decode()}",
                "screenshot_b": f"data:image/png;base64,{base64.b64encode(img_b).decode()}",
            }
        except Exception as e:
            raise _http_err(500, str(e)) from e

    return router
