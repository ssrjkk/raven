from __future__ import annotations

import asyncio
import contextlib
import re
import ssl as ssl_module
from collections.abc import Awaitable
from typing import Any

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.channel_config import get_channel_config, has_any_channel
from raven.core.models import IncomingMessage, Message

# Ports reserved for implicit-TLS IRCds; plaintext on them is almost always a mistake.
TLS_PORTS = frozenset({5697, 6697, 6699, 7000})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
MAX_LINE = 400
# CR and LF terminate IRC frames, so any control character in outbound text is a command-injection vector.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def parse_port(raw: str | None) -> int:
    if raw is None:
        return 6697
    try:
        port = int(raw)
    except ValueError as ex:
        raise ValueError(f"IRC_PORT must be an integer, got {raw!r}") from ex
    if not 1 <= port <= 65535:
        raise ValueError(f"IRC_PORT must be between 1 and 65535, got {port}")
    return port


def use_tls(port: int, raw: str | None) -> bool:
    """TLS unless IRC_TLS says otherwise; ports outside TLS_PORTS default to plain."""
    if raw is None:
        return port in TLS_PORTS
    return raw.strip().lower() in TRUE_VALUES


def is_safe_target(target: str) -> bool:
    """A PRIVMSG/JOIN argument must be a single token, or a crafted session id could inject IRC commands."""
    return bool(target) and not _CONTROL_RE.search(target) and " " not in target and "," not in target


class IRCChannel(EnterpriseChannel):
    channel_id = "irc"

    def __init__(self):
        super().__init__()
        self._nick = "raven-bot"
        self._server = "irc.libera.chat"
        self._port = 6697
        self._password = ""
        self._user = "raven-bot"
        self._realname = "Raven AI"
        self._tls = True
        self._channels_to_join: list[str] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reconnect_delay = 1.0
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._configured = False
        self._running = False
        self._identified = False

    async def _start(self):
        cfg = get_channel_config("irc")
        self._server = cfg.get("server", "irc.libera.chat")
        self._port = parse_port(cfg.get("port"))
        self._nick = cfg.get("nick", "raven-bot")
        self._user = cfg.get("nick", "raven-bot")[:16]
        self._password = cfg.get("password", "")
        self._tls = use_tls(self._port, cfg.get("tls"))
        self._channels_to_join = [ch.strip() for ch in cfg.get("channels", "#raven").split(",") if ch.strip()]
        self._configured = has_any_channel("irc")
        if not self._configured:
            logger.info("[irc] no IRC_* configuration — adapter stays idle")
            return
        logger.info("[irc] connecting to {}:{} over {}", self._server, self._port, "TLS" if self._tls else "plaintext")
        await self._connect()
        self._running = True
        self._spawn(self._read_loop())

    async def _stop(self):
        self._running = False
        writer = self._writer
        if writer is not None:
            with contextlib.suppress(Exception):
                self._write_line("QUIT")
                await writer.drain()
        pending = list(self._bg_tasks)
        self._bg_tasks.clear()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self._drop_connection()
        logger.info("[irc] channel stopped")

    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _connect(self) -> None:
        context = ssl_module.create_default_context() if self._tls else None
        self._reader, self._writer = await asyncio.open_connection(self._server, self._port, ssl=context)
        self._identified = False
        self._write_line(f"NICK {self._nick}")
        self._write_line(f"USER {self._user} 0 * :{self._realname}")
        await self._flush()

    async def _drop_connection(self) -> None:
        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    def _write_line(self, line: str) -> None:
        if self._writer is None:
            raise ConnectionError("[irc] not connected")
        self._writer.write(_CONTROL_RE.sub(" ", line).encode("utf-8", errors="replace") + b"\r\n")

    async def _flush(self) -> None:
        if self._writer is not None:
            await self._writer.drain()

    async def _read_loop(self) -> None:
        while self._running:
            reader = self._reader
            if reader is None:
                break
            try:
                line = await reader.readline()
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError) as ex:
                logger.warning("[irc] read failed: {}", ex)
                await self._reconnect()
                continue
            if not line:
                logger.warning("[irc] server closed the connection")
                await self._reconnect()
                continue
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._handle_raw(text)

    async def _reconnect(self) -> None:
        self._stats["reconnects"] += 1
        await self._drop_connection()
        while self._running:
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)
            try:
                await self._connect()
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError) as ex:
                logger.warning("[irc] reconnect to {}:{} failed: {}", self._server, self._port, ex)
                continue
            self._reconnect_delay = 1.0
            logger.info("[irc] reconnected to {}:{}", self._server, self._port)
            return

    _PRIVMSG_RE = re.compile(r":(\S+)!\S+ PRIVMSG (\S+) :(.+)")

    def _handle_raw(self, line: str):
        if line.startswith("PING") and self._writer:
            self._write_line(line.replace("PING", "PONG", 1))
            return
        tokens = line.split()
        if len(tokens) >= 3 and tokens[1] == "001":
            # JOIN and NickServ only work once the server has finished registration.
            if self._password and not self._identified:
                self._identified = True
                self._write_line(f"PRIVMSG NickServ :IDENTIFY {self._password}")
            for room in self._channels_to_join:
                if is_safe_target(room):
                    self._write_line(f"JOIN {room}")
                else:
                    logger.warning("[irc] skipping unusable channel name {!r}", room)
            return
        m = self._PRIVMSG_RE.match(line)
        if m:
            nick, target, text = m.group(1), m.group(2), m.group(3)
            if nick != self._nick and text and self._handler:
                self._stats["received"] += 1
                self._spawn(
                    self._handler(
                        IncomingMessage(
                            channel="irc",
                            user_id=nick,
                            session_id=f"irc:{target}:{nick}",
                            text=text,
                            metadata={"channel": target, "server": self._server},
                        )
                    )
                )

    async def handle_message(self, nick: str, channel: str, text: str):
        if not self._handler or not self._ready or nick == self._nick:
            return
        self._stats["received"] += 1
        await self._handler(
            IncomingMessage(
                channel="irc",
                user_id=nick,
                session_id=f"irc:{channel}:{nick}",
                text=text,
                metadata={"channel": channel, "server": self._server},
            )
        )

    async def _send_message(self, session_id: str, message: Message):
        parts = session_id.split(":")
        target = parts[1] if len(parts) >= 2 else ""
        if not is_safe_target(target):
            logger.warning("[irc] refusing to send to unusable target {!r}", target)
            return
        if self._writer is None:
            raise ConnectionError("[irc] not connected")
        text = _CONTROL_RE.sub(" ", message.content)[:MAX_LINE]
        self._write_line(f"PRIVMSG {target} :{text}")
        await self._flush()

    async def health_check(self) -> bool:
        if not self._configured:
            return self._ready
        return self._ready and self._writer is not None

    def stats(self) -> dict[str, Any]:
        return {**super().stats(), "connected": self._writer is not None, "tls": self._tls}
