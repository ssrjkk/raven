from __future__ import annotations

from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.email_config import email_config
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import email as email_tools

_EMAIL_ENV = (
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_PORT",
    "EMAIL_SMTP_USER",
    "EMAIL_SMTP_PASS",
    "EMAIL_IMAP_HOST",
    "EMAIL_IMAP_PORT",
    "EMAIL_IMAP_USER",
    "EMAIL_IMAP_PASS",
    "EMAIL_INBOX_FOLDER",
    "EMAIL_POLL_INTERVAL",
)


@pytest.fixture(autouse=True)
def _clean_email_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _EMAIL_ENV:
        monkeypatch.delenv(name, raising=False)


def _raw_email(from_addr: str = "a@b.com", subject: str = "Hi", body: str = "text") -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg.set_content(body)
    return msg.as_bytes()


def _smtp_config(monkeypatch: pytest.MonkeyPatch, *, port: str = "587") -> None:
    monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_SMTP_PORT", port)
    monkeypatch.setenv("EMAIL_SMTP_USER", "sender@example.com")
    monkeypatch.setenv("EMAIL_SMTP_PASS", "secret")


def _imap_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("EMAIL_IMAP_USER", "reader@example.com")
    monkeypatch.setenv("EMAIL_IMAP_PASS", "secret")


def _enable_smtp(monkeypatch: pytest.MonkeyPatch, *, send: AsyncMock | None = None) -> AsyncMock:
    send = send or AsyncMock(return_value=None)
    monkeypatch.setattr(email_tools, "_AIOSMTP_AVAILABLE", True)
    monkeypatch.setattr(email_tools, "aiosmtplib", SimpleNamespace(send=send), raising=False)
    return send


def _enable_imap(
    monkeypatch: pytest.MonkeyPatch,
    search: tuple[str, list[bytes]] = ("OK", [b"1 2 3"]),
    fetch: tuple[str, object] | list[tuple[str, object]] | None = None,
    login_error: Exception | None = None,
) -> MagicMock:
    client = MagicMock()
    client.wait_hello_from_server = AsyncMock()
    client.login = AsyncMock(side_effect=login_error) if login_error else AsyncMock()
    client.select = AsyncMock()
    client.search = AsyncMock(return_value=search)
    if fetch is None:
        client.fetch = AsyncMock(return_value=("OK", [(b"1", _raw_email())]))
    elif isinstance(fetch, list):
        client.fetch = AsyncMock(side_effect=fetch)
    else:
        client.fetch = AsyncMock(return_value=fetch)
    client.logout = AsyncMock()
    _imap_config(monkeypatch)
    monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", True)
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(email_tools, "aioimaplib", SimpleNamespace(IMAP4_SSL=factory), raising=False)
    client.imap_factory = factory
    return client


class TestEmailConfig:
    def test_defaults_when_unset(self) -> None:
        cfg = email_config()
        assert cfg.smtp_port == 587
        assert cfg.imap_port == 993
        assert cfg.inbox_folder == "INBOX"
        assert cfg.poll_interval == 30
        assert cfg.smtp_ready is False
        assert cfg.imap_ready is False

    def test_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _smtp_config(monkeypatch, port="465")
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.example.com")
        monkeypatch.setenv("EMAIL_IMAP_PORT", "143")
        monkeypatch.setenv("EMAIL_INBOX_FOLDER", "Archive")
        monkeypatch.setenv("EMAIL_POLL_INTERVAL", "5")
        cfg = email_config()
        assert cfg.smtp_host == "smtp.example.com"
        assert cfg.smtp_port == 465
        assert cfg.smtp_pass == "secret"
        assert cfg.imap_port == 143
        assert cfg.inbox_folder == "Archive"
        assert cfg.poll_interval == 5
        assert cfg.smtp_ready is True
        assert cfg.imap_ready is False

    def test_non_numeric_port_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMAIL_SMTP_PORT", "not-a-port")
        with pytest.raises(ValueError, match="EMAIL_SMTP_PORT must be an integer"):
            email_config()


class TestEmailSend:
    async def test_requires_aiosmtplib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOSMTP_AVAILABLE", False)
        result = await email_tools.email_send("to@example.com", "subj", "body")
        assert "aiosmtplib is required" in result
        assert "raven-agent[email]" in result

    async def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_smtp(monkeypatch)
        result = await email_tools.email_send("to@example.com", "subj", "body")
        assert result == "[error] SMTP not configured. Set EMAIL_SMTP_HOST and EMAIL_SMTP_USER env vars."

    async def test_starttls_on_submission_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        send = _enable_smtp(monkeypatch)
        _smtp_config(monkeypatch)
        result = await email_tools.email_send("to@example.com", "Hello", "World")
        assert result == "Email sent to to@example.com: 'Hello'"
        call = send.await_args
        assert call is not None
        assert call.kwargs["hostname"] == "smtp.example.com"
        assert call.kwargs["port"] == 587
        assert call.kwargs["username"] == "sender@example.com"
        assert call.kwargs["password"] == "secret"
        assert call.kwargs["use_tls"] is False
        assert call.kwargs["start_tls"] is True

    async def test_implicit_tls_on_465(self, monkeypatch: pytest.MonkeyPatch) -> None:
        send = _enable_smtp(monkeypatch)
        _smtp_config(monkeypatch, port="465")
        await email_tools.email_send("to@example.com", "Hello", "World")
        call = send.await_args
        assert call is not None
        assert call.kwargs["use_tls"] is True
        assert call.kwargs["start_tls"] is False

    async def test_send_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_smtp(monkeypatch, send=AsyncMock(side_effect=RuntimeError("connection refused")))
        _smtp_config(monkeypatch)
        result = await email_tools.email_send("to@example.com", "Hello", "World")
        assert result == "[error] Failed to send email: connection refused"

    async def test_invalid_port_surfaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_smtp(monkeypatch)
        monkeypatch.setenv("EMAIL_SMTP_PORT", "ldap")
        with pytest.raises(ValueError, match="EMAIL_SMTP_PORT"):
            await email_tools.email_send("to@example.com", "Hello", "World")


class TestEmailInbox:
    async def test_requires_aioimaplib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", False)
        result = await email_tools.email_inbox()
        assert "aioimaplib is required" in result
        assert "raven-agent[email]" in result

    async def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", True)
        result = await email_tools.email_inbox()
        assert result == "[error] IMAP not configured. Set EMAIL_IMAP_HOST and EMAIL_IMAP_USER env vars."

    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _enable_imap(monkeypatch)
        result = await email_tools.email_inbox()
        assert "Recent emails (last 3 of 3 total)" in result
        assert "From: a@b.com" in result
        assert "Subject: Hi" in result
        client.logout.assert_awaited_once()

    async def test_connects_to_configured_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EMAIL_IMAP_PORT", "1143")
        monkeypatch.setenv("EMAIL_INBOX_FOLDER", "Agent mail")
        client = _enable_imap(monkeypatch)
        await email_tools.email_inbox()
        client.imap_factory.assert_called_once_with("imap.example.com", 1143)
        client.select.assert_awaited_once_with("Agent mail")

    async def test_search_not_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _enable_imap(monkeypatch, search=("NO", []))
        result = await email_tools.email_inbox()
        assert result == "[error] Failed to search inbox."
        client.logout.assert_awaited_once()

    async def test_no_message_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_imap(monkeypatch, search=("OK", []))
        result = await email_tools.email_inbox()
        assert result == "Recent emails (last 0 of 0 total):\n"

    async def test_limit_clamps_to_one_not_the_whole_mailbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _enable_imap(monkeypatch, search=("OK", [b"1 2 3"]))
        result = await email_tools.email_inbox(limit=0)
        assert "Recent emails (last 1 of 3 total)" in result
        assert client.fetch.await_count == 1

    async def test_limit_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ids = b" ".join(str(i).encode() for i in range(1, 61))
        client = _enable_imap(monkeypatch, search=("OK", [ids]))
        result = await email_tools.email_inbox(limit=1000)
        assert "Recent emails (last 50 of 60 total)" in result
        assert client.fetch.await_count == 50

    async def test_fetch_not_ok_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_imap(monkeypatch, search=("OK", [b"1"]), fetch=("NO", []))
        result = await email_tools.email_inbox()
        assert "Recent emails (last 1 of 1 total)" in result
        assert "From:" not in result

    async def test_fetch_no_data_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_imap(monkeypatch, search=("OK", [b"1"]), fetch=("OK", []))
        result = await email_tools.email_inbox()
        assert "Recent emails (last 1 of 1 total)" in result
        assert "From:" not in result

    async def test_message_without_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_imap(monkeypatch, search=("OK", [b"1"]), fetch=("OK", [(b"1", b"\r\n\r\n")]))
        result = await email_tools.email_inbox()
        assert "From: unknown" in result
        assert "Subject: (no subject)" in result

    async def test_login_failure_logs_out_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _enable_imap(monkeypatch, login_error=RuntimeError("auth denied"))
        result = await email_tools.email_inbox()
        assert result == "[error] Failed to read inbox: auth denied"
        client.logout.assert_awaited_once()


class TestEmailConfigStatus:
    def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOSMTP_AVAILABLE", False)
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", False)
        result = email_tools.email_config_status()
        assert "SMTP: not configured" in result
        assert "IMAP: not configured" in result
        assert "SMTP lib: not installed" in result
        assert "IMAP lib: not installed" in result

    def test_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _smtp_config(monkeypatch)
        _imap_config(monkeypatch)
        monkeypatch.setattr(email_tools, "_AIOSMTP_AVAILABLE", True)
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", True)
        result = email_tools.email_config_status()
        assert "SMTP: configured (smtp.example.com)" in result
        assert "IMAP: configured (imap.example.com)" in result
        assert "SMTP lib: available" in result
        assert "IMAP lib: available" in result


class TestRegisterEmailTools:
    def test_registers_all_tools(self) -> None:
        registry = ToolRegistry()
        email_tools.register_email_tools(registry)
        assert registry.count == 3
        send_tool = registry.get("email_send")
        inbox_tool = registry.get("email_inbox")
        status_tool = registry.get("email_config_status")
        assert send_tool is not None
        assert inbox_tool is not None
        assert status_tool is not None
        assert send_tool.handler is email_tools.email_send
        assert inbox_tool.handler is email_tools.email_inbox
        assert status_tool.handler is email_tools.email_config_status
