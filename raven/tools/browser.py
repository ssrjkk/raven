from __future__ import annotations

import asyncio

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def browser_open(url: str) -> str:
    import webbrowser

    webbrowser.open(url)
    return f"Opened {url} in browser"


async def browser_screenshot(url: str, timeout: int = 15) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "Playwright not installed. Install: pip install playwright && playwright install"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        await asyncio.sleep(2)
        screenshot = await page.screenshot(full_page=False)
        await browser.close()

    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "screenshot.png"
    tmp.write_bytes(screenshot)
    return f"Screenshot saved to {tmp} ({len(screenshot)} bytes)"


def register_browser_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="browser_open",
            description="Open a URL in the default browser",
            parameters={
                "url": {"type": "string", "description": "URL to open", "required": True},
            },
            handler=browser_open,
            category="web",
        )
    )
    registry.register(
        ToolSpec(
            name="browser_screenshot",
            description="Take a screenshot of a webpage using headless browser",
            parameters={
                "url": {"type": "string", "description": "URL to capture", "required": True},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "required": False},
            },
            handler=browser_screenshot,
            category="web",
            timeout=30,
        )
    )
