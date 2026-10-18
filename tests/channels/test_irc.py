from __future__ import annotations

import asyncio
import ssl as ssl_module
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest

from raven.channels.irc.channel import IRCChannel, parse_port, use_tls
from raven.core.models import Message

IRC_VARS = ("IRC_SERVER", "IRC_PORT", "IRC_TLS", "IRC_NICK", "IRC_PASSWORD", "IRC_CHANNELS")
WELCOME = ":irc.test 001 raven-bot :Welcome to the test network"


class FakeIRCServer:
    """A loopback IRCd: records every line the client sends and lets tests push server lines."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.connections = 0
        self.port = 0
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = int(self._server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writer = writer
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                self.lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        finally:
            writer.close()

    async def send(self, line: str) -> None:
        assert self._writer is not None, "the channel has not connected yet"
        self._writer.write(line.encode() + b"\r\n")
        await self._writer.drain()

    def drop(self) -> None:
        """Hang up on the client so the reconnect path runs."""
        assert self._writer is not None
        self._writer.close()
        self._writer = None

    async def wait_for(self, prefix: str, count: int = 1) -> None:
        for _ in range(400):
            if sum(1 for line in self.lines if line.startswith(prefix)) >= count:
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"client never sent {prefix!r} x{count}; got {self.lines}")


class RecordingWriter:
    def __init__(self) -> None:
        self.buffer = b""

    def write(self, data: bytes) -> None:
        self.buffer += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _clean_irc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in IRC_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
async def server() -> AsyncIterator[FakeIRCServer]:
    fake = FakeIRCServer()
    await fake.start()
    yield fake
    await fake.close()


async def _started(monkeypatch: pytest.MonkeyPatch, srv: FakeIRCServer, **env: str) -> IRCChannel:
    monkeypatch.setenv("IRC_SERVER", "127.0.0.1")
    monkeypatch.setenv("IRC_PORT", str(srv.port))
    monkeypatch.setenv("IRC_TLS", "0")
    monkeypatch.setenv("IRC_NICK", env.pop("nick", "raven-bot"))
    monkeypatch.setenv("IRC_CHANNELS", env.pop("channels", "#raven"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    channel = IRCChannel()
    await channel.start()
    return channel


async def _registered(monkeypatch: pytest.MonkeyPatch, srv: FakeIRCServer, **env: str) -> IRCChannel:
    channel = await _started(monkeypatch, srv, **env)
    await srv.wait_for("USER")
    await srv.send(WELCOME)
    return channel


async def _awaited(handler: AsyncMock, count: int = 1) -> None:
    for _ in range(400):
        if handler.await_count >= count:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"handler awaited {handler.await_count} times, expected {count}")


def test_tls_is_implied_by_the_port() -> None:
    assert use_tls(6697, None) is True
    assert use_tls(6667, None) is False
    assert use_tls(6697, "0") is False
    assert use_tls(6667, "on") is True


@pytest.mark.parametrize("raw,expected", [(None, 6697), ("6667", 6667), ("1", 1), ("65535", 65535)])
def test_parse_port_accepts_valid_numbers(raw: str | None, expected: int) -> None:
    assert parse_port(raw) == expected


@pytest.mark.parametrize("raw", ["66abc", "", "0", "70000", "-1"])
def test_parse_port_rejects_nonsense(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_port(raw)


@pytest.mark.asyncio
async def test_unconfigured_channel_never_dials_out(monkeypatch: pytest.MonkeyPatch) -> None:
    open_connection = AsyncMock()
    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    channel = IRCChannel()
    await channel.start()
    open_connection.assert_not_awaited()
    assert channel._writer is None
    # Idle-but-configured-elsewhere must not look unhealthy to the guardian, or it restart-loops.
    assert await channel.health_check() is True
    assert channel.stats()["connected"] is False
    await channel.stop()


@pytest.mark.asyncio
async def test_tls_context_is_passed_to_the_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_open(host: str, port: int, *, ssl: ssl_module.SSLContext | None = None):
        captured["host"] = host
        captured["port"] = port
        captured["ssl"] = ssl
        return asyncio.StreamReader(), RecordingWriter()

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    monkeypatch.setenv("IRC_SERVER", "irc.libera.chat")
    monkeypatch.setenv("IRC_PORT", "6697")
    channel = IRCChannel()
    await channel.start()
    assert captured["host"] == "irc.libera.chat"
    assert captured["port"] == 6697
    assert isinstance(captured["ssl"], ssl_module.SSLContext)
    await channel.stop()

    monkeypatch.setenv("IRC_TLS", "0")
    channel = IRCChannel()
    await channel.start()
    assert captured["ssl"] is None
    await channel.stop()


@pytest.mark.asyncio
async def test_invalid_port_fails_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRC_SERVER", "127.0.0.1")
    monkeypatch.setenv("IRC_PORT", "not-a-port")
    channel = IRCChannel()
    with pytest.raises(ValueError, match="IRC_PORT"):
        await channel.start()
    assert channel._ready is False


@pytest.mark.asyncio
async def test_unreachable_server_fails_the_start(
    monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer
) -> None:
    port = server.port
    await server.close()  # nothing is listening on the port any more
    monkeypatch.setenv("IRC_SERVER", "127.0.0.1")
    monkeypatch.setenv("IRC_PORT", str(port))
    monkeypatch.setenv("IRC_TLS", "0")
    channel = IRCChannel()
    with pytest.raises(OSError):
        await channel.start()
    assert channel._ready is False


@pytest.mark.asyncio
async def test_registration_handshake_joins_only_after_the_welcome(
    monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer
) -> None:
    channel = await _started(monkeypatch, server, channels="#raven,#help")
    await server.wait_for("USER")
    assert [line for line in server.lines if line.startswith("JOIN")] == []

    await server.send(WELCOME)
    await server.wait_for("JOIN #raven")
    await server.wait_for("JOIN #help")
    assert server.lines[0].startswith("NICK ")
    assert server.lines[1].startswith("USER raven-bot 0 * :")
    await channel.stop()


@pytest.mark.asyncio
async def test_password_is_sent_to_nickserv_after_the_welcome(
    monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer
) -> None:
    channel = await _registered(monkeypatch, server, IRC_PASSWORD="s3cret")
    await server.wait_for("PRIVMSG NickServ :IDENTIFY s3cret")
    await channel.stop()


@pytest.mark.asyncio
async def test_inbound_privmsg_is_dispatched(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    handler = AsyncMock()
    channel = await _started(monkeypatch, server)
    await channel.on_message(handler)
    await server.wait_for("USER")
    await server.send(WELCOME)
    await server.send(":alice!alice@irc.test PRIVMSG #raven :hello raven")
    await _awaited(handler)

    event = handler.await_args_list[0].args[0]
    assert event.channel == "irc"
    assert event.user_id == "alice"
    assert event.session_id == "irc:#raven:alice"
    assert event.text == "hello raven"
    assert event.metadata == {"channel": "#raven", "server": "127.0.0.1"}
    assert channel.stats()["received"] == 1
    await channel.stop()


@pytest.mark.asyncio
async def test_own_lines_are_not_dispatched(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    handler = AsyncMock()
    channel = await _started(monkeypatch, server, nick="raven-bot")
    await channel.on_message(handler)
    await server.wait_for("USER")
    await server.send(WELCOME)
    await server.send(":raven-bot!raven@irc.test PRIVMSG #raven :echo of my own reply")
    await asyncio.sleep(0.05)
    handler.assert_not_awaited()
    await channel.stop()


@pytest.mark.asyncio
async def test_ping_is_answered_with_pong(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _registered(monkeypatch, server)
    await server.send("PING :irc.test")
    await server.wait_for("PONG :irc.test")
    await channel.stop()


@pytest.mark.asyncio
async def test_outbound_reply_reaches_the_server(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _registered(monkeypatch, server)
    await server.wait_for("JOIN")
    message = Message(session_id="irc:#raven:alice", channel="irc", role="assistant", content="hi alice")
    await channel.send("irc:#raven:alice", message)
    await server.wait_for("PRIVMSG #raven :hi alice")
    await channel.stop()


@pytest.mark.asyncio
async def test_outbound_text_cannot_inject_irc_commands(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _registered(monkeypatch, server)
    await server.wait_for("JOIN")
    smuggled = "one\r\nQUIT\r\nx"
    message = Message(session_id="irc:#raven:alice", channel="irc", role="assistant", content=smuggled)
    await channel.send("irc:#raven:alice", message)
    await server.wait_for("PRIVMSG")
    assert server.lines.count("QUIT") == 0
    assert not any(line == "x" for line in server.lines)
    assert any("one" in line and "QUIT" in line and "x" in line for line in server.lines)
    await channel.stop()


@pytest.mark.asyncio
async def test_unsafe_target_is_refused(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _registered(monkeypatch, server)
    await server.wait_for("JOIN")
    for session_id in ("irc::alice", "irc:#two words:alice", "irc:#a,b:alice"):
        await channel.send(session_id, Message(session_id=session_id, channel="irc", role="assistant", content="boom"))
    await asyncio.sleep(0.05)
    assert [line for line in server.lines if line.startswith("PRIVMSG #")] == []
    await channel.stop()


@pytest.mark.asyncio
async def test_send_without_a_connection_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRC_SERVER", "127.0.0.1")
    monkeypatch.setenv("IRC_NICK", "raven-bot")
    channel = IRCChannel()
    channel._configured = True
    channel._ready = True
    message = Message(session_id="irc:#raven:alice", channel="irc", role="assistant", content="hi")
    with pytest.raises(ConnectionError):
        await channel._send_message("irc:#raven:alice", message)
    await channel.send("irc:#raven:alice", message)
    assert channel.stats()["failed"] == 1
    assert await channel.health_check() is False


@pytest.mark.asyncio
async def test_connection_loss_is_recovered(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _registered(monkeypatch, server)
    await server.wait_for("JOIN")
    channel._reconnect_delay = 0.01
    server.drop()

    await server.wait_for("NICK", 2)
    assert channel.stats()["reconnects"] >= 1
    assert channel._reader is not None

    # The fresh connection re-registers, so inbound traffic works again.
    await server.send(WELCOME)
    await server.send(":alice!alice@irc.test PRIVMSG #raven :still here")
    handler = AsyncMock()
    await channel.on_message(handler)
    await _awaited(handler)
    await channel.stop()


@pytest.mark.asyncio
async def test_quit_is_sent_on_stop(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _registered(monkeypatch, server)
    await server.wait_for("JOIN")
    await channel.stop()
    await server.wait_for("QUIT")
    assert channel._ready is False
    assert channel._writer is None


@pytest.mark.asyncio
async def test_handle_message_api_dispatches_and_skips_self() -> None:
    handler = AsyncMock()
    channel = IRCChannel()
    await channel.on_message(handler)
    channel._ready = True
    await channel.handle_message("alice", "#raven", "hello")
    handler.assert_awaited_once()
    event = handler.await_args_list[0].args[0]
    assert event.channel == "irc"
    assert event.user_id == "alice"
    assert event.session_id == "irc:#raven:alice"

    await channel.handle_message("raven-bot", "#raven", "hello")
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_list_skips_unusable_names(monkeypatch: pytest.MonkeyPatch, server: FakeIRCServer) -> None:
    channel = await _started(monkeypatch, server, channels="#ok,#bad name, ,#also-ok")
    await server.wait_for("USER")
    await server.send(WELCOME)
    await server.wait_for("JOIN #ok")
    await server.wait_for("JOIN #also-ok")
    assert not [line for line in server.lines if line.startswith("JOIN #bad")]
    await channel.stop()
