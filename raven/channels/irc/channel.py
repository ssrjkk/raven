from __future__ import annotations

import asyncio
import contextlib
import re

from loguru import logger

from raven.channels.enterprise_base import EnterpriseChannel
from raven.core.channel_config import get_channel_config
from raven.core.models import IncomingMessage, Message


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
        self._channels_to_join: list[str] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reconnect_delay = 1.0
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def _start(self):
        cfg = get_channel_config("irc")
        self._server = cfg.get("server", "irc.libera.chat")
        self._port = int(cfg.get("port", "6697"))
        self._nick = cfg.get("nick", "raven-bot")
        self._password = cfg.get("password", "")
        self._user = cfg.get("nick", "raven-bot")
        self._realname = "Raven AI"
        self._channels_to_join = cfg.get("channels", "#raven").split(",")
        self._reconnect_delay = 1.0

    async def _stop(self):
        pending = list(self._bg_tasks)
        self._bg_tasks.clear()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        writer = self._writer
        self._writer = None
        self._reader = None
        logger.info("[irc] channel stopped")
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    async def _connect_irc(self):
        loop = asyncio.get_running_loop()
        self._reader, self._writer = await asyncio.open_connection(self._server, self._port, loop=loop)
        self._writer.write(f"NICK {self._nick}\r\n".encode())
        self._writer.write(f"USER {self._user} 0 * :{self._realname}\r\n".encode())
        await self._writer.drain()
        if self._password:
            self._writer.write(f"PRIVMSG NickServ :IDENTIFY {self._password}\r\n".encode())
            await self._writer.drain()
        for ch in self._channels_to_join:
            self._writer.write(f"JOIN {ch}\r\n".encode())
        await self._writer.drain()
        self._reconnect_delay = 1.0
        task = asyncio.create_task(self._read_loop())
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _read_loop(self):
        while self._ready and self._reader:
            try:
                line = (await self._reader.readline()).decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self._handle_raw(line)
            except Exception as e:
                if self._ready:
                    logger.warning("[irc] read error: {} — reconnecting", e)
                    self._stats["reconnects"] += 1
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, 60)
                    with contextlib.suppress(ConnectionError, OSError):
                        old = self._writer
                        if old is not None:
                            with contextlib.suppress(Exception):
                                old.close()
                                await old.wait_closed()
                        self._reader, self._writer = await asyncio.open_connection(self._server, self._port)

    _PRIVMSG_RE = re.compile(r":(\S+)!\S+ PRIVMSG (\S+) :(.+)")

    def _handle_raw(self, line: str):
        if line.startswith("PING") and self._writer:
            self._writer.write(line.replace("PING", "PONG").encode() + b"\r\n")
        m = self._PRIVMSG_RE.match(line)
        if m:
            nick, target, text = m.group(1), m.group(2), m.group(3)
            if nick != self._nick and text and self._handler:
                self._stats["received"] += 1
                task = asyncio.ensure_future(
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
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)

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
        target = parts[1] if len(parts) >= 2 else None
        if not target:
            return
        if self._writer:
            text = message.content[:400].replace("\n", " ")
            self._writer.write(f"PRIVMSG {target} :{text}\r\n".encode())
            await self._writer.drain()
