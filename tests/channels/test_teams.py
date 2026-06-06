from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.teams.channel import TeamsChannel
from raven.core.models import Message


@pytest.mark.asyncio
async def test_teams_start():
    c = TeamsChannel()
    await c.start()
    assert c._ready


@pytest.mark.asyncio
async def test_teams_stop():
    c = TeamsChannel()
    c._ready = True
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_teams_handle_webhook():
    handler = AsyncMock()
    c = TeamsChannel()
    await c.on_message(handler)
    await c.start()
    body = {"text": "hello teams", "from": {"id": "user1"}, "conversation": {"id": "conv1"}}
    result = await c.handle_webhook(body)
    assert result
    handler.assert_awaited_once()
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "teams"
    assert event.text == "hello teams"


@pytest.mark.asyncio
async def test_teams_handle_webhook_no_text():
    handler = AsyncMock()
    c = TeamsChannel()
    await c.on_message(handler)
    await c.start()
    result = await c.handle_webhook({"text": ""})
    assert not result


@pytest.mark.asyncio
async def test_teams_send():
    c = TeamsChannel()
    await c.start()
    msg = Message(session_id="t:c:u", channel="teams", role="assistant", content="r")
    await c.send("t:c:u", msg)
