from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.gateway.channel_manager import ChannelManager
from raven.core.gateway.message_processor import MessageProcessor
from raven.core.metrics import MetricsCollector
from raven.core.models import IncomingMessage


@pytest.fixture
def mock_db():
    db = AsyncMock()
    session = MagicMock()
    session.id = "sess1"
    session.channel = "mock"
    session.user_id = "u1"
    session.sandbox_policy = None
    db.get_or_create_session = AsyncMock(return_value=session)
    db.get_session_messages = AsyncMock(return_value=[])
    db.replace_session_messages = AsyncMock()
    return db


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    agent = MagicMock()

    async def _run(text, confirm_fn=None, history=None):
        yield "Hello "
        yield "world"

    agent.run = _run
    reg.create_agent = MagicMock(return_value=agent)
    return reg


@pytest.fixture
def mock_channels():
    cm = AsyncMock(spec=ChannelManager)
    channel = MagicMock()
    channel.send_stream = AsyncMock()
    cm.get = AsyncMock(return_value=channel)
    return cm, channel


@pytest.fixture
def mock_metrics():
    m = MagicMock(spec=MetricsCollector)
    m.inc = MagicMock()
    m.observe = MagicMock()
    return m


def _make_send():
    return AsyncMock()


@pytest.mark.asyncio
async def test_process_sends_streaming_response(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")

    send_fn.assert_called()
    mock_metrics.inc.assert_any_call("messages_sent", {"channel": "mock"})


@pytest.mark.asyncio
async def test_process_non_streaming(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, channel = mock_channels
    del channel.send_stream
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")

    send_fn.assert_called_once()
    call_args = send_fn.call_args
    assert call_args[0][2]


@pytest.mark.asyncio
async def test_process_empty_response(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    async def empty_run(text, confirm_fn=None, history=None):
        return
        yield  # pragma: no cover

    mock_registry.create_agent.return_value.run = empty_run
    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")

    send_fn.assert_not_called()


@pytest.mark.asyncio
async def test_process_timeout(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    async def slow_run(text, confirm_fn=None, history=None):
        await asyncio.sleep(999)
        yield "late"

    mock_registry.create_agent.return_value.run = slow_run
    with patch("raven.core.gateway.message_processor.settings") as mock_settings:
        mock_settings.agent_token_timeout = 0.01
        event = IncomingMessage(channel="mock", user_id="u1", text="hi")
        await processor.process(event, "sess1")

    assert send_fn.call_count >= 1
    call_args = [c[0] for c in send_fn.call_args_list]
    timeout_sent = any("timed out" in str(a) for a in call_args)
    assert timeout_sent


@pytest.mark.asyncio
async def test_process_mid_stream_error(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    async def error_run(text, confirm_fn=None, history=None):
        yield "partial"
        raise ValueError("oops")  # pragma: no cover
        yield  # pragma: no cover

    mock_registry.create_agent.return_value.run = error_run
    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")

    mock_metrics.inc.assert_any_call("message_processing_errors", {"channel": "mock"})
    assert send_fn.call_count >= 1


@pytest.mark.asyncio
async def test_manage_context_skips_when_no_ctxmgr(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    await processor._manage_context("sess1", [])
    mock_db.get_session_messages.assert_not_called()


@pytest.mark.asyncio
async def test_manage_context_below_threshold(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    ctxmgr = MagicMock()
    ctxmgr.estimate_tokens = AsyncMock(return_value=100)
    ctxmgr._config = MagicMock()
    ctxmgr._config.max_tokens = 100000
    ctxmgr._config.warning_threshold = 0.8
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, ctxmgr, mock_metrics, send_fn)

    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "some content"
    await processor._manage_context("sess1", [mock_msg])
    ctxmgr.manage.assert_not_called()


@pytest.mark.asyncio
async def test_manage_context_above_threshold(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    ctxmgr = MagicMock()
    ctxmgr.estimate_tokens = AsyncMock(return_value=90000)
    ctxmgr._config = MagicMock()
    ctxmgr._config.max_tokens = 100000
    ctxmgr._config.warning_threshold = 0.8
    ctxmgr.manage = AsyncMock(return_value=[{"role": "user", "content": "summary"}])
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, ctxmgr, mock_metrics, send_fn)

    mock_msg = MagicMock()
    mock_msg.role = "user"
    mock_msg.content = "some content"
    await processor._manage_context("sess1", [mock_msg])
    ctxmgr.manage.assert_called_once()
    mock_db.replace_session_messages.assert_called_once_with("sess1", [{"role": "user", "content": "summary"}])


@pytest.mark.asyncio
async def test_manage_context_no_messages(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    ctxmgr = MagicMock()
    ctxmgr.estimate_tokens = AsyncMock(return_value=0)
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, ctxmgr, mock_metrics, send_fn)

    mock_db.get_session_messages = AsyncMock(return_value=[])
    await processor._manage_context("sess1", [])
    ctxmgr.estimate_tokens.assert_not_called()


@pytest.mark.asyncio
async def test_process_passes_managed_history_to_agent(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    ctxmgr = MagicMock()
    ctxmgr.estimate_tokens = AsyncMock(return_value=90000)
    ctxmgr._config = MagicMock(max_tokens=100000, warning_threshold=0.8)
    ctxmgr.manage = AsyncMock(return_value=[{"role": "user", "content": "summary"}])
    processor = MessageProcessor(mock_db, mock_registry, cm, ctxmgr, mock_metrics, send_fn)

    captured: dict[str, Any] = {}

    async def capture_run(text, confirm_fn=None, history=None):
        captured["history"] = history
        yield "ok"

    mock_registry.create_agent.return_value.run = capture_run
    mock_db.get_session_messages = AsyncMock(
        return_value=[MagicMock(role="user", content="old turn", created_at=0, metadata=None)]
    )
    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")

    assert captured["history"] == [{"role": "user", "content": "summary"}]
    mock_db.replace_session_messages.assert_called_once_with("sess1", [{"role": "user", "content": "summary"}])


@pytest.mark.asyncio
async def test_process_full_history_passed_when_no_ctxmgr(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, _ = mock_channels
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    captured: dict[str, Any] = {}

    async def capture_run(text, confirm_fn=None, history=None):
        captured["history"] = history
        yield "ok"

    mock_registry.create_agent.return_value.run = capture_run
    mock_db.get_session_messages = AsyncMock(
        return_value=[MagicMock(role="user", content="first", created_at=0, metadata=None)]
    )
    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")

    assert captured["history"] == [{"role": "user", "content": "first"}]


@pytest.mark.asyncio
async def test_confirm_fn(mock_db, mock_registry, mock_channels, mock_metrics):
    cm, channel = mock_channels
    channel.ask_confirmation = AsyncMock(return_value=True)
    send_fn = _make_send()
    processor = MessageProcessor(mock_db, mock_registry, cm, None, mock_metrics, send_fn)

    captured_confirm = None

    async def capture_run(text, confirm_fn=None, history=None):
        nonlocal captured_confirm
        captured_confirm = confirm_fn
        return
        yield  # pragma: no cover

    agent = mock_registry.create_agent.return_value
    agent.run = capture_run
    event = IncomingMessage(channel="mock", user_id="u1", text="hi")
    await processor.process(event, "sess1")
    if captured_confirm:
        result = await captured_confirm("shell", {"cmd": "ls"})
        assert result is True
