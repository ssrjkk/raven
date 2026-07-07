from __future__ import annotations

import pytest

from ravencode.runtime.browser import browser_close


class TestBrowserCore:
    @pytest.mark.asyncio
    async def test_browser_close_when_not_started(self):
        result = await browser_close()
        assert "closed" in result.lower()
