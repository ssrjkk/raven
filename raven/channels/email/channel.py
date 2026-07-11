from __future__ import annotations

import asyncio
import contextlib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from loguru import logger

from raven.channels.base import BaseChannel, MessageHandler
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


class EmailChannel(BaseChannel):
    channel_id: str = "email"

    def __init__(
        self,
        imap_host: str = "",
        imap_port: int = 993,
        imap_user: str = "",
        imap_pass: str = "",
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_pass: str = "",
        poll_interval: int = 30,
        inbox_folder: str = "INBOX",
    ) -> None:
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._imap_user = imap_user
        self._imap_pass = imap_pass
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_user = smtp_user
        self._smtp_pass = smtp_pass
        self._poll_interval = poll_interval
        self._inbox_folder = inbox_folder

        self._imap_client: Any = None
        self._handler: MessageHandler | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._ready = False
        self._last_uid: int = 0

    async def connect(self) -> None:
        if not _AIOIMAP_AVAILABLE:
            logger.warning("[email] aioimaplib not available — install with 'pip install aioimaplib'")
            return
        if not self._imap_host or not self._imap_user:
            logger.warning("[email] IMAP not configured —  set EMAIL_IMAP_HOST/EMAIL_IMAP_USER")
            return
        try:
            self._imap_client = aioimaplib.IMAP4_SSL(self._imap_host, self._imap_port)
            await self._imap_client.wait_hello_from_server()
            await self._imap_client.login(self._imap_user, self._imap_pass)
            await self._imap_client.select(self._inbox_folder)
            self._ready = True
            logger.info("[email] Connected to IMAP {}:{} as {}", self._imap_host, self._imap_port, self._imap_user)
        except Exception as e:
            logger.error("[email] IMAP connect failed: {}", e)
            self._ready = False

    async def disconnect(self) -> None:
        self._ready = False
        if self._imap_client:
            try:
                await self._imap_client.logout()
            except Exception as e:
                logger.debug("[email] IMAP logout: {}", e)
            self._imap_client = None

    async def send(self, session_id: str, message: Message) -> None:
        if not _AIOSMTP_AVAILABLE:
            logger.warning("[email] aiosmtplib not available — cannot send")
            return
        if not self._smtp_host or not self._smtp_user:
            logger.warning("[email] SMTP not configured")
            return
        try:
            to_addr = session_id  # session_id is the recipient email
            msg = MIMEMultipart()
            msg["From"] = self._smtp_user
            msg["To"] = to_addr
            msg["Subject"] = "Re: Raven AI"
            msg.attach(MIMEText(message.content or "", "plain"))
            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
                username=self._smtp_user,
                password=self._smtp_pass,
                start_tls=True,
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
            logger.info("[email] Polling started (interval={}s)", self._poll_interval)

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
            await asyncio.sleep(self._poll_interval)

    async def _check_inbox(self) -> None:
        if not self._imap_client or not self._handler:
            return
        status, data = await self._imap_client.search("UNSEEN")
        if status != "OK":
            return
        msg_ids = data[0].split() if data else []
        for mid in msg_ids[-5:]:  # max 5 at a time
            typ, msg_data = await self._imap_client.fetch(mid, "(RFC822)")
            if typ != "OK":
                continue
            raw_email = msg_data[0][1] if msg_data else b""
            if not raw_email:
                continue
            try:
                parsed = email.message_from_bytes(raw_email)
                subject = parsed.get("Subject", "")
                from_addr = parsed.get("From", "")
                body = ""
                payload: Any = None
                if parsed.is_multipart():
                    for part in parsed.walk():
                        if part.get_content_type() == "text/plain":
                            payload = part.get_payload(decode=True)
                            break
                else:
                    payload = parsed.get_payload(decode=True)
                if isinstance(payload, bytes):
                    body = payload.decode("utf-8", errors="replace")
                if from_addr and body:
                    incoming = IncomingMessage(
                        channel="email",
                        session_id=from_addr,
                        user_id=from_addr,
                        text=body.strip(),
                        metadata={"subject": subject},
                    )
                    await self._handler(incoming)
            except Exception as e:
                logger.warning("[email] Failed to parse message: {}", e)

    async def health_check(self) -> bool:
        return self._ready
