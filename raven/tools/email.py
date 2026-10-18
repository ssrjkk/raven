from __future__ import annotations

from contextlib import suppress

from loguru import logger

from raven.core.email_config import email_config
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


async def email_send(to: str, subject: str, body: str) -> str:
    if not _AIOSMTP_AVAILABLE:
        return "[error] aiosmtplib is required. Install with: pip install 'raven-agent[email]'"
    config = email_config()
    if not config.smtp_ready:
        return "[error] SMTP not configured. Set EMAIL_SMTP_HOST and EMAIL_SMTP_USER env vars."
    try:
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg["From"] = config.smtp_user
        msg["To"] = to
        msg["Subject"] = subject
        await aiosmtplib.send(
            msg,
            hostname=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user,
            password=config.smtp_pass,
            use_tls=config.smtp_over_tls,
            start_tls=not config.smtp_over_tls,
        )
        return f"Email sent to {to}: '{subject}'"
    except Exception as e:
        logger.error("Email send failed: {}", e)
        return f"[error] Failed to send email: {e}"


async def email_inbox(limit: int = 10) -> str:
    if not _AIOIMAP_AVAILABLE:
        return "[error] aioimaplib is required. Install with: pip install 'raven-agent[email]'"
    config = email_config()
    if not config.imap_ready:
        return "[error] IMAP not configured. Set EMAIL_IMAP_HOST and EMAIL_IMAP_USER env vars."
    import email

    # A zero or negative slice bound would fetch the whole mailbox: msg_ids[-0:] is msg_ids[:].
    limit = max(1, min(int(limit), 50))
    client = aioimaplib.IMAP4_SSL(config.imap_host, config.imap_port)
    try:
        await client.wait_hello_from_server()
        await client.login(config.imap_user, config.imap_pass)
        await client.select(config.inbox_folder)
        status, data = await client.search("ALL")
        if status != "OK":
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
        return "\n".join(lines)
    except Exception as e:
        logger.error("Email inbox failed: {}", e)
        return f"[error] Failed to read inbox: {e}"
    finally:
        with suppress(Exception):
            await client.logout()


def email_config_status() -> str:
    config = email_config()
    parts = [
        "Email Configuration:",
        f"  SMTP: {'configured' if config.smtp_ready else 'not configured'} ({config.smtp_host or '—'})",
        f"  IMAP: {'configured' if config.imap_ready else 'not configured'} ({config.imap_host or '—'})",
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
