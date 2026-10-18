from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from raven.channels.matrix.channel import MatrixChannel
from raven.core.models import IncomingMessage, Message

MATRIX_VARS = ("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN")


@pytest.fixture(autouse=True)
def _clean_matrix_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in MATRIX_VARS:
        monkeypatch.delenv(var, raising=False)


class _FakeMatrix:
    """Serves canned responses for `_matrix_get` and remembers every path that was requested."""

    def __init__(self, responses: list[dict[str, object] | Exception]) -> None:
        self.responses = responses
        self.paths: list[str] = []

    async def request(self, path: str) -> dict[str, object]:
        self.paths.append(path)
        # A real /sync blocks for `timeout=30000`; an instant-returning fake would starve the event loop.
        await asyncio.sleep(0.001)
        if not self.responses:
            return {"next_batch": "idle", "rooms": {}}
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _text_event(sender: str = "@user:example.com", body: str = "Hello Matrix") -> dict[str, object]:
    return {
        "type": "m.room.message",
        "sender": sender,
        "event_id": "$event1",
        "content": {"msgtype": "m.text", "body": body},
    }


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
async def test_unconfigured_channel_never_contacts_a_homeserver(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeMatrix([{"user_id": "@raven:example.com"}])
    monkeypatch.setattr(MatrixChannel, "_matrix_get", lambda self, path: fake.request(path))
    channel = MatrixChannel()
    await channel.start()
    assert fake.paths == []
    assert channel._sync_task is None
    await channel.stop()


@pytest.mark.asyncio
async def test_start_launches_the_sync_loop_and_dispatches_events(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATRIX_HOMESERVER", "https://matrix.example.com")
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "tok")
    fake = _FakeMatrix(
        [
            {"user_id": "@raven:example.com"},
            {
                "next_batch": "s1",
                "rooms": {"join": {"!room:example.com": {"timeline": {"events": [_text_event()]}}}},
            },
        ]
    )
    handler = AsyncMock()
    monkeypatch.setattr(MatrixChannel, "_matrix_get", lambda self, path: fake.request(path))
    channel = MatrixChannel()
    await channel.on_message(handler)

    await channel.start()
    try:
        for _ in range(400):
            if handler.await_count:
                break
            await asyncio.sleep(0.005)
    finally:
        await channel.stop()

    assert handler.await_count == 1
    event: IncomingMessage = handler.await_args_list[0].args[0]
    assert event.channel == "matrix"
    assert event.user_id == "@user:example.com"
    assert event.session_id == "matrix:!room:example.com:@user:example.com"
    assert event.text == "Hello Matrix"
    assert channel._sync_token == "s1"
    assert fake.paths[0] == "/_matrix/client/v3/account/whoami"
    assert fake.paths[1].startswith("/_matrix/client/v3/sync?timeout=30000")


@pytest.mark.asyncio
async def test_sync_survives_a_failed_long_poll(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATRIX_HOMESERVER", "https://matrix.example.com")
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "tok")
    fake = _FakeMatrix([{"user_id": "@raven:example.com"}, ConnectionError("homeserver unreachable")])
    monkeypatch.setattr(MatrixChannel, "_matrix_get", lambda self, path: fake.request(path))
    channel = MatrixChannel()
    await channel.start()
    task = channel._sync_task
    assert task is not None

    for _ in range(400):
        if channel.stats()["reconnects"] >= 1:
            break
        await asyncio.sleep(0.005)
    assert channel.stats()["reconnects"] == 1
    assert not task.done()
    await channel.stop()


@pytest.mark.asyncio
async def test_stop_cancels_the_sync_task(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATRIX_HOMESERVER", "https://matrix.example.com")
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "tok")
    fake = _FakeMatrix([{"user_id": "@raven:example.com"}])
    monkeypatch.setattr(MatrixChannel, "_matrix_get", lambda self, path: fake.request(path))
    channel = MatrixChannel()
    await channel.start()
    task = channel._sync_task
    assert task is not None
    await channel.stop()
    assert task.done()
    assert channel._sync_task is None


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
    ev: IncomingMessage = handler.await_args[0][0]  # type: ignore[index]
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
