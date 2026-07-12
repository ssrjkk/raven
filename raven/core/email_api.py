from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

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


def _get_config() -> dict[str, str]:
    try:
        from raven.core.config import settings
        return {
            "smtp_host": getattr(settings, "EMAIL_SMTP_HOST", ""),
            "smtp_port": str(getattr(settings, "EMAIL_SMTP_PORT", "587")),
            "smtp_user": getattr(settings, "EMAIL_SMTP_USER", ""),
            "smtp_pass": getattr(settings, "EMAIL_SMTP_PASS", ""),
            "imap_host": getattr(settings, "EMAIL_IMAP_HOST", ""),
            "imap_port": str(getattr(settings, "EMAIL_IMAP_PORT", "993")),
            "imap_user": getattr(settings, "EMAIL_IMAP_USER", ""),
            "imap_pass": getattr(settings, "EMAIL_IMAP_PASS", ""),
        }
    except Exception as e:
        logger.debug("Failed to load email config from settings: {}", e)
        return {}


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
        config = _get_config()
        smtp_host = config.get("smtp_host", "")
        smtp_user = config.get("smtp_user", "")
        smtp_pass = config.get("smtp_pass", "")
        smtp_port = int(config.get("smtp_port", "587"))
        if not smtp_host or not smtp_user:
            raise HTTPException(400, "SMTP not configured")
        try:
            from email.mime.text import MIMEText
            msg = MIMEText(req.body)
            msg["From"] = smtp_user
            msg["To"] = req.to
            msg["Subject"] = req.subject
            await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=smtp_user,
                password=smtp_pass,
                start_tls=True,
            )
            return {"success": True, "to": req.to, "subject": req.subject}
        except Exception as e:
            logger.error("Email send API error: {}", e)
            raise HTTPException(500, str(e)) from e

    @router.get("/inbox")
    async def inbox(limit: int = 10):
        if not _AIOIMAP_AVAILABLE:
            raise HTTPException(400, "aioimaplib not installed")
        config = _get_config()
        imap_host = config.get("imap_host", "")
        imap_user = config.get("imap_user", "")
        imap_pass = config.get("imap_pass", "")
        imap_port = int(config.get("imap_port", "993"))
        if not imap_host or not imap_user:
            raise HTTPException(400, "IMAP not configured")
        try:
            import email
            client = aioimaplib.IMAP4_SSL(imap_host, imap_port)
            await client.wait_hello_from_server()
            await client.login(imap_user, imap_pass)
            await client.select("INBOX")
            status, data = await client.search("ALL")
            if status != "OK":
                await client.logout()
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
                    body = payload.decode("utf-8", errors="replace")[:500]
                emails.append({
                    "from": parsed.get("From", ""),
                    "subject": parsed.get("Subject", ""),
                    "date": parsed.get("Date", ""),
                    "body_preview": body,
                })
            await client.logout()
            return {"emails": emails, "total": len(msg_ids)}
        except Exception as e:
            logger.error("Email inbox API error: {}", e)
            raise HTTPException(500, str(e)) from e

    @router.get("/config")
    async def config():
        cfg = _get_config()
        return {
            "smtp_configured": bool(cfg.get("smtp_host")),
            "imap_configured": bool(cfg.get("imap_host")),
            "smtp_lib_available": _AIOSMTP_AVAILABLE,
            "imap_lib_available": _AIOIMAP_AVAILABLE,
            "smtp_host": cfg.get("smtp_host", ""),
            "imap_host": cfg.get("imap_host", ""),
        }

    return router
