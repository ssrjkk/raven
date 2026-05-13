from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.signal.channel import SignalChannel
from raven.core.models import Message


@pytest.mark.asyncio
async def test_signal_start():
    c = SignalChannel()
    await c.start()
    assert c._ready


@pytest.mark.asyncio
async def test_signal_stop():
    c = SignalChannel()
    c._ready = True
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_signal_handle_webhook():
    handler = AsyncMock()
    c = SignalChannel()
    await c.on_message(handler)
    c._ready = True
    body = {"envelope": {"source": "+1234567890", "dataMessage": {"message": "Hello Signal"}}}
    result = await c.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event = handler.await_args[0][0]
    assert event.channel == "signal"
    assert event.text == "Hello Signal"


@pytest.mark.asyncio
async def test_signal_handle_webhook_no_text():
    handler = AsyncMock()
    c = SignalChannel()
    await c.on_message(handler)
    c._ready = True
    result = await c.handle_webhook({"envelope": {}})
    assert not result


@pytest.mark.asyncio
async def test_signal_send():
    c = SignalChannel()
    c._ready = True
    msg = Message(session_id="s:u", channel="signal", role="assistant", content="r")
    await c.send("s:u", msg)
