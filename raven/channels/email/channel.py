from __future__ import annotations

import asyncio
import contextlib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from typing import Any

from loguru import logger

from raven.channels.base import BaseChannel, MessageHandler
from raven.core.email_config import EmailConfig, email_config
from raven.core.email_mime import plain_body
from raven.core.models import IncomingMessage, Message

try:
    import aioimaplib

    _AIOIMAP_AVAILABLE = True
except ImportError:
    _AIOIMAP_AVAILABLE = False

try:
    import aiosmtplib

    _AIOSMTP_AVAILABLE = True
except ImportError:
    _AIOSMTP_AVAILABLE = False

SESSION_PREFIX = "email:"
SESSION_SUFFIX = ":default"
# One poll reads at most this many unseen messages, so a flooded inbox cannot stall the loop.
POLL_BATCH = 5


def session_id_for(address: str) -> str:
    return f"{SESSION_PREFIX}{address}{SESSION_SUFFIX}"


def address_for_session(session_id: str) -> str:
    """Recover the peer address from a session id; empty when the id is not an email session."""
    if not session_id.startswith(SESSION_PREFIX):
        return ""
    return session_id[len(SESSION_PREFIX) :].removesuffix(SESSION_SUFFIX)


class EmailChannel(BaseChannel):
    channel_id: str = "email"

    def __init__(self, config: EmailConfig | None = None) -> None:
        self._config = config
        self._imap_client: Any = None
        self._handler: MessageHandler | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._ready = False

    @property
    def _cfg(self) -> EmailConfig:
        if self._config is None:
            self._config = email_config()
        return self._config

    async def connect(self) -> None:
        if not _AIOIMAP_AVAILABLE:
            logger.warning("[email] aioimaplib not available — install with pip install 'raven-agent[email]'")
            return
        cfg = self._cfg
        if not cfg.imap_ready:
            logger.warning("[email] IMAP not configured — set EMAIL_IMAP_HOST/EMAIL_IMAP_USER")
            return
        try:
            self._imap_client = aioimaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
            await self._imap_client.wait_hello_from_server()
            await self._imap_client.login(cfg.imap_user, cfg.imap_pass)
            await self._imap_client.select(cfg.inbox_folder)
            self._ready = True
            logger.info("[email] Connected to IMAP {}:{} as {}", cfg.imap_host, cfg.imap_port, cfg.imap_user)
        except Exception as e:
            logger.error("[email] IMAP connect failed: {}", e)
            self._ready = False

    async def disconnect(self) -> None:
        self._ready = False
        if self._imap_client:
            with contextlib.suppress(Exception):
                await self._imap_client.logout()
            self._imap_client = None

    async def send(self, session_id: str, message: Message) -> None:
        if not _AIOSMTP_AVAILABLE:
            logger.warning("[email] aiosmtplib not available — cannot send")
            return
        cfg = self._cfg
        if not cfg.smtp_ready:
            logger.warning("[email] SMTP not configured — set EMAIL_SMTP_HOST/EMAIL_SMTP_USER")
            return
        to_addr = address_for_session(session_id)
        if not to_addr:
            logger.warning("[email] Session {} carries no recipient address", session_id)
            return
        try:
            msg = MIMEMultipart()
            msg["From"] = cfg.smtp_user
            msg["To"] = to_addr
            msg["Subject"] = "Re: Raven AI"
            msg.attach(MIMEText(message.content or "", "plain"))
            await aiosmtplib.send(
                msg,
                hostname=cfg.smtp_host,
                port=cfg.smtp_port,
                username=cfg.smtp_user,
                password=cfg.smtp_pass,
                use_tls=cfg.smtp_over_tls,
                start_tls=not cfg.smtp_over_tls,
            )
            logger.info("[email] Sent reply to {}", to_addr)
        except Exception as e:
            logger.error("[email] SMTP send failed: {}", e)

    async def on_message(self, handler: MessageHandler) -> None:
        self._handler = handler

    async def start(self) -> None:
        await self.connect()
        if self._ready:
            self._poll_task = asyncio.create_task(self._poll_loop())
            logger.info("[email] Polling started (interval={}s)", self._cfg.poll_interval)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        await self.disconnect()
        logger.info("[email] channel stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._check_inbox()
            except Exception as e:
                logger.error("[email] Poll error: {}", e)
            await asyncio.sleep(self._cfg.poll_interval)

    async def _check_inbox(self) -> None:
        if not self._imap_client or not self._handler:
            return
        status, data = await self._imap_client.search("UNSEEN")
        if status != "OK":
            return
        msg_ids = data[0].split() if data else []
        for mid in msg_ids[-POLL_BATCH:]:
            await self._handle_one(mid)

    async def _handle_one(self, mid: bytes) -> None:
        client, handler = self._imap_client, self._handler
        if client is None or handler is None:
            return
        typ, msg_data = await client.fetch(mid, "(RFC822)")
        if typ != "OK":
            return
        raw_email = msg_data[0][1] if msg_data else b""
        if not raw_email:
            return
        address, subject, body = "", "", ""
        try:
            parsed = email.message_from_bytes(raw_email)
            # parseaddr echoes malformed headers back verbatim; without a domain there is nothing to reply to.
            candidate = parseaddr(parsed.get("From", ""))[1]
            address = candidate if "@" in candidate else ""
            subject = parsed.get("Subject", "")
            body = plain_body(parsed)
        except Exception as e:
            logger.warning("[email] Failed to parse message {}: {}", mid, e)
        # Seen is set before the dispatch: an unreadable header would otherwise be refetched
        # on every poll, and a handler failure is already logged by the gateway.
        try:
            await client.store(mid.decode() if isinstance(mid, bytes) else str(mid), "+FLAGS", "\\Seen")
        except Exception as e:
            logger.warning("[email] Could not mark message {} seen: {}", mid, e)
        if not address or not body.strip():
            return
        await handler(
            IncomingMessage(
                channel=self.channel_id,
                session_id=session_id_for(address),
                user_id=address,
                text=body.strip(),
                metadata={"subject": subject},
            )
        )

    async def health_check(self) -> bool:
        return self._ready
