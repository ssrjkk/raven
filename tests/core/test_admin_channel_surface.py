"""The admin channel surface against the handle the shipped gateway actually builds.

Measured on a live gateway on 2026-11-18: `/api/admin/channels` answered 500 (`ChannelManager` has no
`.items()`), `/api/admin/system/status` answered 500 (`len()` of the same), and both
`/api/admin/channels/{id}` routes answered 500 because `ChannelManager.get()` is a coroutine -- a coroutine is
always truthy, so an unknown id never reached its 404 and a known one crashed reading attributes off it. The
suite was green throughout: its `channels` fixture was a plain `dict`, and a dict answers `.items()`, `len()`
and a synchronous `.get()` -- every shape the routes assumed.

The readiness the routes report is the other half of the promise, measured here on 2026-11-18: both read
`ch._ready` off the object, with a fallback that is `True` in the list route and `False` in the detail route.
Neither is the answer the channel gives about itself.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.channels.base import BaseChannel, MessageHandler
from raven.core.admin_api import create_admin_router
from raven.core.db import Database
from raven.core.gateway.channel_manager import ChannelManager
from raven.core.gateway.gateway import Gateway
from raven.core.models import Message
from raven.core.plugin_loader import PluginLoader


class _Channel(BaseChannel):
    """A channel the surface can describe: id, readiness, stats, start/stop.

    It is a `BaseChannel`, not a shape that merely fits, because `ChannelManager.register` takes the contract
    and stores what it is handed -- the same substitution of a lookalike for the real handle that this suite
    exists to catch. The traffic half of the contract is declared empty: none of these routes opens, closes or
    sends through a channel, and a double that answered those calls would be claiming behaviour under test.
    Readiness is answered through `health_check()`, the way `raven/channels/webchat/channel.py:407` answers it,
    so the surface is measured against the same contract a shipped channel presents.
    """

    def __init__(self, channel_id: str, ready: bool = True) -> None:
        self.channel_id = channel_id
        self._ready = ready

    def stats(self) -> dict[str, int]:
        return {"messages": 3}

    async def health_check(self) -> bool:
        return self._ready

    async def start(self) -> None:
        self._ready = True

    async def stop(self) -> None:
        self._ready = False

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def send(self, session_id: str, message: Message) -> None: ...

    async def on_message(self, handler: MessageHandler) -> None: ...


@pytest.fixture
def production_gateway(tmp_path: Path) -> Gateway:
    """The object `raven start` runs, built the way `gateway_runner` builds it."""
    db = SimpleNamespace(health_check=lambda: True, db_path=str(tmp_path / "gw.db"))
    loader = SimpleNamespace(tools={})
    # Neither handle is touched while these routes answer, so the placeholder is stated as one instead of
    # asking `Gateway` to accept anything: the object it is told to hold is the one it declares.
    return Gateway(db=cast("Database", db), plugin_loader=cast("PluginLoader", loader))


def _client(gateway: Gateway) -> TestClient:
    app = FastAPI()
    app.include_router(create_admin_router(lambda: gateway.channels, lambda: gateway.registry, lambda: gateway))
    return TestClient(app)


def _register(gateway: Gateway, *channels: _Channel) -> None:
    async def _all() -> None:
        for channel in channels:
            await gateway.channels.register(channel)

    asyncio.run(_all())


def test_the_handle_the_gateway_builds_is_a_manager_and_not_a_dict(production_gateway: Gateway) -> None:
    manager = production_gateway.channels
    assert isinstance(manager, ChannelManager)
    for dict_shape in ("items", "keys", "__len__"):
        assert not hasattr(manager, dict_shape), f"ChannelManager grew {dict_shape}, so the dict fixture fits again"
    assert inspect.iscoroutinefunction(manager.get), "ChannelManager.get went sync, so the coroutine bug fits again"


def test_the_channel_list_answers_on_the_production_handle(production_gateway: Gateway) -> None:
    _register(production_gateway, _Channel("telegram"), _Channel("web", ready=False))
    body = _client(production_gateway).get("/api/admin/channels").json()
    assert {c["id"] for c in body} == {"telegram", "web"}
    assert next(c for c in body if c["id"] == "web")["ready"] is False


def test_one_channel_answers_on_the_production_handle(production_gateway: Gateway) -> None:
    _register(production_gateway, _Channel("telegram"))
    client = _client(production_gateway)
    detail = client.get("/api/admin/channels/telegram").json()
    assert detail["type"] == "_Channel"
    assert detail["stats"] == {"messages": 3}
    assert client.get("/api/admin/channels/nope").status_code == 404


def test_restart_answers_on_the_production_handle(production_gateway: Gateway) -> None:
    channel = _Channel("telegram")
    _register(production_gateway, channel)
    client = _client(production_gateway)
    assert client.post("/api/admin/channels/telegram/restart").status_code == 200
    assert channel._ready is True
    assert client.post("/api/admin/channels/nope/restart").status_code == 404


def test_system_status_counts_channels_on_the_production_handle(production_gateway: Gateway) -> None:
    _register(production_gateway, _Channel("telegram"), _Channel("web"))
    body = _client(production_gateway).get("/api/admin/system/status").json()
    assert body["channels"] == 2
    assert body["agents"] == len(production_gateway.registry.list_agents())


def test_a_plain_dict_would_not_answer_any_of_them(production_gateway: Gateway) -> None:
    """The guard's bite, measured: the fixture the suite used is not interchangeable with the handle.

    Swapping in a dict -- exactly what the old fixture passed -- makes these routes raise, which is what makes
    the assertions above a check of the production object rather than of any object answering `.get()`.
    """
    # The plant is the old fixture itself, and the cast is the lie it told: a dict is not a `ChannelManager`,
    # which is exactly why the three requests below have to raise instead of answering.
    production_gateway.channels = cast("ChannelManager", {"telegram": _Channel("telegram")})
    client = TestClient(_client(production_gateway), raise_server_exceptions=False)
    assert client.get("/api/admin/channels").status_code == 500
    assert client.get("/api/admin/system/status").status_code == 500
    assert client.post("/api/admin/channels/telegram/restart").status_code == 500


class _TransportGone(_Channel):
    """A channel that was started and has since lost its transport -- the state its probe calls unhealthy.

    `TelegramChannel.health_check` is `self._ready and self._app is not None`
    (`raven/channels/telegram/channel.py:106`), `IRCChannel`'s is `self._ready and self._writer is not None`
    (`raven/channels/irc/channel.py:236`) and `DiscordChannel`'s `self._ready and self._bot is not None`
    (`raven/channels/discord/channel.py:284`). `start()` leaves the flag set, so the flag is not what these
    channels answer when asked whether they are healthy -- their probe is.
    """

    async def health_check(self) -> bool:
        return False


class _KeepsItsOwnState(_Channel):
    """A channel that exposes readiness only through the contract's probe and sets no `_ready` attribute.

    `BaseChannel` requires no flag, so this is a channel built to the contract as written.
    """

    def __init__(self, channel_id: str, healthy: bool = True) -> None:
        self.channel_id = channel_id
        self._healthy = healthy

    async def health_check(self) -> bool:
        return self._healthy


def test_the_readiness_the_console_paints_is_the_answer_the_channel_gives(production_gateway: Gateway) -> None:
    """`web/src/pages/Admin.tsx:182` paints one dot from this field, and that dot is the operator's only view.

    Both routes have to report the channel's own probe. They read `ch._ready`, so a channel with no socket
    behind its handle answered `ready: true` and the console painted it green.
    """
    _register(production_gateway, _TransportGone("telegram"))
    client = _client(production_gateway)
    listed = next(ch for ch in client.get("/api/admin/channels").json() if ch["id"] == "telegram")
    detail = client.get("/api/admin/channels/telegram").json()
    assert listed["ready"] is False, f"the list paints a channel with no transport as ready: {listed}"
    assert detail["ready"] is False, f"the detail page paints it as ready: {detail}"


def test_the_two_channel_routes_answer_readiness_once(production_gateway: Gateway) -> None:
    """The same object was healthy and unhealthy depending on which route the operator opened.

    The fallback for a channel that keeps its state behind the probe was `True` in `/channels` and `False` in
    `/channels/{channel_id}` -- two lines of one file, each guessing at the other's question. Both now ask the
    channel, and the guard runs the probe in both directions because a fallback that always agreed with a
    `False` would pass on the accident of one value.
    """
    for name, healthy in (("silent", False), ("speaking", True)):
        _register(production_gateway, _KeepsItsOwnState(name, healthy=healthy))
        client = _client(production_gateway)
        listed = next(ch for ch in client.get("/api/admin/channels").json() if ch["id"] == name)
        detail = client.get(f"/api/admin/channels/{name}").json()
        assert listed["ready"] == detail["ready"], (
            f"{name}: the list said {listed['ready']}, the detail {detail['ready']}"
        )
        assert listed["ready"] is healthy, f"{name}: both routes said {listed['ready']} to a probe of {healthy}"
