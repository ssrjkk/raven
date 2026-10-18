from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.core.email_config import email_config
from raven.core.email_mime import plain_body

try:
    import aiosmtplib

    _AIOSMTP_AVAILABLE = True
except ImportError:
    _AIOSMTP_AVAILABLE = False

try:
    import aioimaplib

    _AIOIMAP_AVAILABLE = True
except ImportError:
    _AIOIMAP_AVAILABLE = False


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str


def create_email_router() -> APIRouter:
    router = APIRouter(prefix="/api/email", tags=["email"])

    @router.post("/send")
    async def send_email(req: SendEmailRequest):
        if not _AIOSMTP_AVAILABLE:
            raise HTTPException(400, "aiosmtplib not installed")
        config = email_config()
        if not config.smtp_ready:
            raise HTTPException(400, "SMTP not configured")
        try:
            from email.mime.text import MIMEText

            msg = MIMEText(req.body)
            msg["From"] = config.smtp_user
            msg["To"] = req.to
            msg["Subject"] = req.subject
            await aiosmtplib.send(
                msg,
                hostname=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_user,
                password=config.smtp_pass,
                use_tls=config.smtp_over_tls,
                start_tls=not config.smtp_over_tls,
            )
            return {"success": True, "to": req.to, "subject": req.subject}
        except Exception as e:
            logger.error("Email send API error: {}", e)
            raise internal_error(e) from e

    @router.get("/inbox")
    async def inbox(limit: int = 10):
        if not _AIOIMAP_AVAILABLE:
            raise HTTPException(400, "aioimaplib not installed")
        config = email_config()
        if not config.imap_ready:
            raise HTTPException(400, "IMAP not configured")
        # A zero or negative slice bound would fetch the whole mailbox: msg_ids[-0:] is msg_ids[:].
        limit = max(1, min(limit, 50))
        client = aioimaplib.IMAP4_SSL(config.imap_host, config.imap_port)
        try:
            import email

            await client.wait_hello_from_server()
            await client.login(config.imap_user, config.imap_pass)
            await client.select(config.inbox_folder)
            status, data = await client.search("ALL")
            if status != "OK":
                return {"emails": [], "total": 0}
            msg_ids = data[0].split() if data else []
            recent = msg_ids[-limit:]
            emails = []
            for mid in recent:
                typ, msg_data = await client.fetch(mid, "(RFC822)")
                if typ != "OK":
                    continue
                raw = msg_data[0][1] if msg_data else b""
                if not raw:
                    continue
                parsed = email.message_from_bytes(raw)
                body = plain_body(parsed)[:500]
                emails.append(
                    {
                        "from": parsed.get("From", ""),
                        "subject": parsed.get("Subject", ""),
                        "date": parsed.get("Date", ""),
                        "body_preview": body,
                    }
                )
            return {"emails": emails, "total": len(msg_ids)}
        except Exception as e:
            logger.error("Email inbox API error: {}", e)
            raise internal_error(e) from e
        finally:
            with suppress(Exception):
                await client.logout()

    @router.get("/config")
    async def config():
        cfg = email_config()
        return {
            "smtp_configured": cfg.smtp_ready,
            "imap_configured": cfg.imap_ready,
            "smtp_lib_available": _AIOSMTP_AVAILABLE,
            "imap_lib_available": _AIOIMAP_AVAILABLE,
            "smtp_host": cfg.smtp_host,
            "imap_host": cfg.imap_host,
        }

    return router
