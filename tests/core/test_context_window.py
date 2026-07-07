from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.core.context_window import ContextWindowConfig, ContextWindowManager


@pytest.fixture
def mock_llm():
    m = AsyncMock()
    m.complete = AsyncMock(return_value=type("R", (), {"content": "summary text", "strip": lambda self: self.content})())
    return m


@pytest.fixture
def mgr(mock_llm):
    config = ContextWindowConfig(max_tokens=1000, warning_threshold=0.3, summarization_threshold=0.6, hard_limit_threshold=0.8, sliding_window_size=4)
    return ContextWindowManager(mock_llm, config)


@pytest.mark.asyncio
async def test_estimate_tokens(mgr):
    msgs = [{"role": "user", "content": "hello world"}, {"role": "assistant", "content": "hi there"}]
    total = await mgr.estimate_tokens(msgs)
    expected = (len("hello world") // 4 + 10) + (len("hi there") // 4 + 10)
    assert total == expected


@pytest.mark.asyncio
async def test_manage_below_warning_returns_unchanged(mgr):
    msgs = [{"role": "user", "content": "short"}]
    result = await mgr.manage(msgs)
    assert result is msgs


@pytest.mark.asyncio
async def test_manage_above_warning_adds_note(mgr):
    msgs = [{"role": "system", "content": "you are a bot"}, {"role": "user", "content": "x" * 1200}]
    result = await mgr.manage(msgs)
    assert any(m.get("role") == "system" and "Note" in m.get("content", "") for m in result)


@pytest.mark.asyncio
async def test_manage_hard_limit_drops_oldest(mgr):
    msgs = [{"role": "user", "content": "x" * 400} for _ in range(20)]
    result = await mgr.manage(msgs)
    assert len(result) < len(msgs)


@pytest.mark.asyncio
async def test_manage_empty_returns_empty(mgr):
    result = await mgr.manage([])
    assert result == []
