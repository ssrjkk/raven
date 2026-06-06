from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.line.channel import LINECChannel
from raven.core.models import Message


@pytest.mark.asyncio
async def test_line_start():
    c = LINECChannel()
    await c.start()
    assert c._ready


@pytest.mark.asyncio
async def test_line_stop():
    c = LINECChannel()
    c._ready = True
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_line_handle_webhook():
    handler = AsyncMock()
    c = LINECChannel()
    await c.on_message(handler)
    await c.start()
    body = {
        "events": [
            {
                "type": "message",
                "replyToken": "r1",
                "source": {"userId": "u1"},
                "message": {"type": "text", "text": "hello line"},
            }
        ]
    }
    result = await c.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "line"
    assert event.text == "hello line"


@pytest.mark.asyncio
async def test_line_handle_webhook_non_text():
    handler = AsyncMock()
    c = LINECChannel()
    await c.on_message(handler)
    await c.start()
    body = {
        "events": [
            {
                "type": "message",
                "source": {"userId": "u1"},
                "message": {"type": "image"},
            }
        ]
    }
    result = await c.handle_webhook(body)
    assert not result


@pytest.mark.asyncio
async def test_line_handle_webhook_empty():
    handler = AsyncMock()
    c = LINECChannel()
    await c.on_message(handler)
    await c.start()
    result = await c.handle_webhook({"events": []})
    assert not result


@pytest.mark.asyncio
async def test_line_send():
    c = LINECChannel()
    await c.start()
    msg = Message(session_id="l:u", channel="line", role="assistant", content="r")
    await c.send("l:u", msg)
