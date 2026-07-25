from __future__ import annotations

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

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
        logger.debug("Email config read failed: {}", e)
        return {}


async def email_send(to: str, subject: str, body: str) -> str:
    if not _AIOSMTP_AVAILABLE:
        return "[error] aiosmtplib is required. Install with: pip install aiosmtplib"
    config = _get_config()
    smtp_host = config.get("smtp_host", "")
    smtp_user = config.get("smtp_user", "")
    smtp_pass = config.get("smtp_pass", "")
    smtp_port = int(config.get("smtp_port", "587"))
    if not smtp_host or not smtp_user:
        return "[error] SMTP not configured. Set EMAIL_SMTP_HOST and EMAIL_SMTP_USER env vars."
    try:
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg["From"] = smtp_user
        msg["To"] = to
        msg["Subject"] = subject
        await aiosmtplib.send(
            msg,
            hostname=smtp_host,
            port=smtp_port,
            username=smtp_user,
            password=smtp_pass,
            start_tls=True,
        )
        return f"Email sent to {to}: '{subject}'"
    except Exception as e:
        logger.error("Email send failed: {}", e)
        return f"[error] Failed to send email: {e}"


async def email_inbox(limit: int = 10) -> str:
    if not _AIOIMAP_AVAILABLE:
        return "[error] aioimaplib is required. Install with: pip install aioimaplib"
    config = _get_config()
    imap_host = config.get("imap_host", "")
    imap_user = config.get("imap_user", "")
    imap_pass = config.get("imap_pass", "")
    imap_port = int(config.get("imap_port", "993"))
    if not imap_host or not imap_user:
        return "[error] IMAP not configured. Set EMAIL_IMAP_HOST and EMAIL_IMAP_USER env vars."
    try:
        import email

        client = aioimaplib.IMAP4_SSL(imap_host, imap_port)
        await client.wait_hello_from_server()
        await client.login(imap_user, imap_pass)
        await client.select("INBOX")
        status, data = await client.search("ALL")
        if status != "OK":
            await client.logout()
            return "[error] Failed to search inbox."
        msg_ids = data[0].split() if data else []
        recent = msg_ids[-limit:]
        lines = [f"Recent emails (last {len(recent)} of {len(msg_ids)} total):\n"]
        for mid in recent:
            typ, msg_data = await client.fetch(mid, "(RFC822)")
            if typ != "OK":
                continue
            raw = msg_data[0][1] if msg_data else b""
            if not raw:
                continue
            parsed = email.message_from_bytes(raw)
            from_addr = parsed.get("From", "unknown")
            subject = parsed.get("Subject", "(no subject)")
            lines.append(f"  From: {from_addr}")
            lines.append(f"  Subject: {subject}")
            lines.append("")
        await client.logout()
        return "\n".join(lines)
    except Exception as e:
        logger.error("Email inbox failed: {}", e)
        return f"[error] Failed to read inbox: {e}"


def email_config_status() -> str:
    config = _get_config()
    parts = [
        "Email Configuration:",
        f"  SMTP: {'configured' if config.get('smtp_host') else 'not configured'} ({config.get('smtp_host', '—')})",
        f"  IMAP: {'configured' if config.get('imap_host') else 'not configured'} ({config.get('imap_host', '—')})",
        f"  SMTP lib: {'available' if _AIOSMTP_AVAILABLE else 'not installed'}",
        f"  IMAP lib: {'available' if _AIOIMAP_AVAILABLE else 'not installed'}",
    ]
    return "\n".join(parts)


def register_email_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="email_send",
            description="Send an email via SMTP",
            parameters={
                "to": {"type": "string", "description": "Recipient email address", "required": True},
                "subject": {"type": "string", "description": "Email subject", "required": True},
                "body": {"type": "string", "description": "Email body text", "required": True},
            },
            handler=email_send,
            category="email",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="email_inbox",
            description="List recent emails from the IMAP inbox",
            parameters={
                "limit": {"type": "integer", "description": "Number of recent emails (default 10)", "required": False},
            },
            handler=email_inbox,
            category="email",
            timeout=30,
        )
    )
    registry.register(
        ToolSpec(
            name="email_config_status",
            description="Check email configuration status",
            parameters={},
            handler=email_config_status,
            category="email",
            timeout=10,
        )
    )
