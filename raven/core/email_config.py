from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from raven.core.channel_config import get_channel_config

SSL_SUBMISSION_PORT = 465


@dataclass(frozen=True)
class EmailConfig:
    """IMAP/SMTP settings as read from the ``EMAIL_*`` environment.

    An empty host means "not configured"; every caller checks ``smtp_ready``/``imap_ready``
    instead of letting a connection error out of an address-less client.
    """

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    inbox_folder: str = "INBOX"
    poll_interval: int = 30

    @property
    def smtp_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_user)

    @property
    def imap_ready(self) -> bool:
        return bool(self.imap_host and self.imap_user)

    @property
    def smtp_over_tls(self) -> bool:
        """465 is the implicit-TLS submission port; anything else upgrades with STARTTLS."""
        return self.smtp_port == SSL_SUBMISSION_PORT


def _int_field(cfg: dict[str, Any], field: str, env_name: str, default: int) -> int:
    raw = cfg.get(field)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw))
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer, got {raw!r}") from exc


def email_config() -> EmailConfig:
    cfg = get_channel_config("email")
    return EmailConfig(
        smtp_host=str(cfg.get("smtp_host", "")),
        smtp_port=_int_field(cfg, "smtp_port", "EMAIL_SMTP_PORT", 587),
        smtp_user=str(cfg.get("smtp_user", "")),
        smtp_pass=str(cfg.get("smtp_pass", "")),
        imap_host=str(cfg.get("imap_host", "")),
        imap_port=_int_field(cfg, "imap_port", "EMAIL_IMAP_PORT", 993),
        imap_user=str(cfg.get("imap_user", "")),
        imap_pass=str(cfg.get("imap_pass", "")),
        inbox_folder=str(cfg.get("inbox_folder", "INBOX")),
        poll_interval=_int_field(cfg, "poll_interval", "EMAIL_POLL_INTERVAL", 30),
    )
