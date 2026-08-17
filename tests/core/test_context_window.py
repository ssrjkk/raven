from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.core.context_window import ContextWindowConfig, ContextWindowManager


@pytest.fixture
def mock_llm():
    m = AsyncMock()
    m.complete = AsyncMock(
        return_value=type("R", (), {"content": "summary text", "strip": lambda self: self.content})()
    )
    return m


@pytest.fixture
def mgr(mock_llm):
    config = ContextWindowConfig(
        max_tokens=1000,
        warning_threshold=0.3,
        summarization_threshold=0.6,
        hard_limit_threshold=0.8,
        sliding_window_size=4,
    )
    return ContextWindowManager(mock_llm, config)


@pytest.mark.asyncio
async def test_estimate_tokens(mgr):
    msgs = [{"role": "user", "content": "hello world"}, {"role": "assistant", "content": "hi there"}]
    total = await mgr.estimate_tokens(msgs)

    def est(s: str) -> int:
        return int(2 + len(s) / 4)  # 2 words + ascii chars/4

    expected = est("hello world") + 10 + est("hi there") + 10
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


@pytest.mark.asyncio
async def test_manage_drops_orphaned_leading_tool_message(mgr):
    # 21 non-system messages: assistant(tool_calls) at 0, tool response at 1, fillers after.
    # Window keeps the last 4 (sliding_window_size) -> the parent is dropped, the tool msg
    # becomes the window's first message and must be trimmed.
    msgs: list[dict[str, object]] = [{"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]}]
    msgs.append({"role": "tool", "tool_call_id": "t1", "content": "result"})
    msgs.extend({"role": "user", "content": "x" * 400} for _ in range(19))
    result = await mgr.manage(msgs)
    assert len(result) == 4
    assert all(m.get("role") != "tool" for m in result)


@pytest.mark.asyncio
async def test_manage_keeps_tool_pair_inside_window(mgr):
    msgs: list[dict[str, object]] = [{"role": "user", "content": "x" * 400} for _ in range(18)]
    msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]})
    msgs.append({"role": "tool", "tool_call_id": "t1", "content": "result"})
    result = await mgr.manage(msgs)
    assert len(result) == 4
    assert [m.get("role") for m in result[-2:]] == ["assistant", "tool"]
