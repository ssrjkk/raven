from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from raven.channels.matrix.channel import MatrixChannel
from raven.core.models import Message, IncomingMessage


@pytest.mark.asyncio
async def test_matrix_start():
    channel = MatrixChannel()
    with patch("raven.channels.matrix.channel.HAS_HTTPX", True):
        await channel.start()
    assert channel._ready


@pytest.mark.asyncio
async def test_matrix_stop():
    channel = MatrixChannel()
    await channel.start()
    await channel.stop()
    assert not channel._ready


@pytest.mark.asyncio
async def test_matrix_handle_webhook_no_handler():
    channel = MatrixChannel()
    await channel.start()
    result = await channel.handle_webhook({"event": {}})
    assert not result


@pytest.mark.asyncio
async def test_matrix_handle_webhook_text():
    handler = AsyncMock()
    channel = MatrixChannel()
    await channel.on_message(handler)
    await channel.start()
    body = {
        "event": {
            "type": "m.room.message",
            "sender": "@user:matrix.org",
            "room_id": "!room:matrix.org",
            "event_id": "$event1",
            "content": {
                "msgtype": "m.text",
                "body": "Hello Matrix",
            },
        }
    }
    result = await channel.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event: IncomingMessage = handler.await_args[0][0]
    assert event.channel == "matrix"
    assert event.user_id == "@user:matrix.org"
    assert event.text == "Hello Matrix"


@pytest.mark.asyncio
async def test_matrix_handle_webhook_non_text():
    handler = AsyncMock()
    channel = MatrixChannel()
    await channel.on_message(handler)
    await channel.start()
    body = {
        "event": {
            "type": "m.room.message",
            "sender": "@user:matrix.org",
            "room_id": "!room:matrix.org",
            "content": {
                "msgtype": "m.image",
                "body": "photo.png",
            },
        }
    }
    result = await channel.handle_webhook(body)
    assert not result
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_matrix_handle_webhook_wrong_type():
    handler = AsyncMock()
    channel = MatrixChannel()
    await channel.on_message(handler)
    await channel.start()
    body = {
        "event": {
            "type": "m.typing",
            "sender": "@user:matrix.org",
            "room_id": "!room:matrix.org",
        }
    }
    result = await channel.handle_webhook(body)
    assert not result


@pytest.mark.asyncio
async def test_matrix_send():
    channel = MatrixChannel()
    resp_mock = MagicMock()
    resp_mock.raise_for_status = MagicMock()
    channel._client = AsyncMock()
    channel._client.put = AsyncMock(return_value=resp_mock)
    channel._ready = True
    msg = Message(session_id="matrix:!room:matrix.org:@user", channel="matrix", role="assistant", content="reply")
    await channel.send("matrix:!room:matrix.org:@user", msg)
    channel._client.put.assert_awaited_once()
    call_kwargs = channel._client.put.call_args[1]
    assert call_kwargs["json"]["msgtype"] == "m.text"
    assert call_kwargs["json"]["body"] == "reply"
