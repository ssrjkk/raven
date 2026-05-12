from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.matrix.channel import MatrixChannel
from raven.core.models import IncomingMessage, Message


@pytest.mark.asyncio
async def test_matrix_start():
    channel = MatrixChannel()
    await channel.start()
    assert channel._ready


@pytest.mark.asyncio
async def test_matrix_stop():
    channel = MatrixChannel()
    await channel.start()
    await channel.stop()
    assert not channel._ready


@pytest.mark.asyncio
async def test_matrix_handle_event():
    handler = AsyncMock()
    channel = MatrixChannel()
    await channel.on_message(handler)
    channel._ready = True
    event = {
        "type": "m.room.message",
        "sender": "@user:matrix.org",
        "room_id": "!room:matrix.org",
        "event_id": "$event1",
        "content": {"msgtype": "m.text", "body": "Hello Matrix"},
    }
    result = await channel.handle_event(event, "!room:matrix.org")
    assert result
    handler.assert_awaited_once()
    ev: IncomingMessage = handler.await_args[0][0]
    assert ev.channel == "matrix"
    assert ev.user_id == "@user:matrix.org"
    assert ev.text == "Hello Matrix"


@pytest.mark.asyncio
async def test_matrix_handle_event_non_text():
    handler = AsyncMock()
    channel = MatrixChannel()
    await channel.on_message(handler)
    channel._ready = True
    event = {
        "type": "m.room.message",
        "sender": "@user:matrix.org",
        "content": {"msgtype": "m.image", "body": "photo.png"},
    }
    result = await channel.handle_event(event, "!room:matrix.org")
    assert not result


@pytest.mark.asyncio
async def test_matrix_handle_event_wrong_type():
    handler = AsyncMock()
    channel = MatrixChannel()
    await channel.on_message(handler)
    channel._ready = True
    event = {"type": "m.typing", "sender": "@user:matrix.org"}
    result = await channel.handle_event(event, "!room:matrix.org")
    assert not result


@pytest.mark.asyncio
async def test_matrix_send():
    channel = MatrixChannel()
    channel._homeserver = "https://matrix.example.com"
    channel._token = "tok"
    channel._ready = True
    msg = Message(session_id="matrix:!room:matrix.org:@user", channel="matrix", role="assistant", content="reply")
    await channel.send("matrix:!room:matrix.org:@user", msg)
