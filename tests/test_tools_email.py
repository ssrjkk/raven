from __future__ import annotations

import sys
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools import email as email_tools


def _config(**overrides: str) -> dict[str, str]:
    base = {
        "smtp_host": "",
        "smtp_port": "587",
        "smtp_user": "",
        "smtp_pass": "",
        "imap_host": "",
        "imap_port": "993",
        "imap_user": "",
        "imap_pass": "",
    }
    base.update(overrides)
    return base


def _raw_email(from_addr: str = "a@b.com", subject: str = "Hi") -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    return msg.as_bytes()


def _enable_smtp(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    send = AsyncMock(return_value=None)
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
    monkeypatch.setattr(email_tools, "_get_config", lambda: _config(imap_host="imap.example.com", imap_user="reader@example.com", imap_pass="secret"))
    monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", True)
    monkeypatch.setattr(email_tools, "aioimaplib", SimpleNamespace(IMAP4_SSL=MagicMock(return_value=client)), raising=False)
    return client


class TestGetConfig:
    def test_reads_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = SimpleNamespace(
            EMAIL_SMTP_HOST="smtp.example.com",
            EMAIL_SMTP_PORT=2525,
            EMAIL_SMTP_USER="sender@example.com",
            EMAIL_SMTP_PASS="smtppass",
            EMAIL_IMAP_HOST="imap.example.com",
            EMAIL_IMAP_PORT=143,
            EMAIL_IMAP_USER="reader@example.com",
            EMAIL_IMAP_PASS="imappass",
        )
        monkeypatch.setattr("raven.core.config.settings", settings)
        cfg = email_tools._get_config()
        assert cfg["smtp_host"] == "smtp.example.com"
        assert cfg["smtp_port"] == "2525"
        assert cfg["smtp_user"] == "sender@example.com"
        assert cfg["smtp_pass"] == "smtppass"
        assert cfg["imap_host"] == "imap.example.com"
        assert cfg["imap_port"] == "143"
        assert cfg["imap_user"] == "reader@example.com"
        assert cfg["imap_pass"] == "imappass"

    def test_reads_defaults_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("raven.core.config.settings", SimpleNamespace())
        cfg = email_tools._get_config()
        assert cfg["smtp_host"] == ""
        assert cfg["smtp_port"] == "587"
        assert cfg["imap_host"] == ""
        assert cfg["imap_port"] == "993"

    def test_config_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "raven.core.config", None)
        assert email_tools._get_config() == {}


class TestEmailSend:
    async def test_requires_aiosmtplib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOSMTP_AVAILABLE", False)
        result = await email_tools.email_send("to@example.com", "subj", "body")
        assert result == "[error] aiosmtplib is required. Install with: pip install aiosmtplib"

    async def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_smtp(monkeypatch)
        monkeypatch.setattr(email_tools, "_get_config", lambda: {"smtp_port": "587"})
        result = await email_tools.email_send("to@example.com", "subj", "body")
        assert result == "[error] SMTP not configured. Set EMAIL_SMTP_HOST and EMAIL_SMTP_USER env vars."

    async def test_send_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        send = _enable_smtp(monkeypatch)
        monkeypatch.setattr(
            email_tools,
            "_get_config",
            lambda: {
                "smtp_host": "smtp.example.com",
                "smtp_port": "465",
                "smtp_user": "sender@example.com",
                "smtp_pass": "secret",
            },
        )
        result = await email_tools.email_send("to@example.com", "Hello", "World")
        assert result == "Email sent to to@example.com: 'Hello'"
        call = send.await_args
        assert call is not None
        assert call.kwargs["hostname"] == "smtp.example.com"
        assert call.kwargs["port"] == 465
        assert call.kwargs["username"] == "sender@example.com"
        assert call.kwargs["password"] == "secret"
        assert call.kwargs["start_tls"] is True

    async def test_send_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        send = _enable_smtp(monkeypatch)
        send.side_effect = RuntimeError("connection refused")
        monkeypatch.setattr(
            email_tools,
            "_get_config",
            lambda: {"smtp_host": "smtp.example.com", "smtp_user": "sender@example.com"},
        )
        result = await email_tools.email_send("to@example.com", "Hello", "World")
        assert result == "[error] Failed to send email: connection refused"

    async def test_invalid_port_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_smtp(monkeypatch)
        monkeypatch.setattr(
            email_tools,
            "_get_config",
            lambda: {"smtp_host": "smtp.example.com", "smtp_port": "not-a-port", "smtp_user": "u"},
        )
        with pytest.raises(ValueError):
            await email_tools.email_send("to@example.com", "Hello", "World")


class TestEmailInbox:
    async def test_requires_aioimaplib(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", False)
        result = await email_tools.email_inbox()
        assert result == "[error] aioimaplib is required. Install with: pip install aioimaplib"

    async def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", True)
        monkeypatch.setattr(email_tools, "_get_config", lambda: {"imap_port": "993"})
        result = await email_tools.email_inbox()
        assert result == "[error] IMAP not configured. Set EMAIL_IMAP_HOST and EMAIL_IMAP_USER env vars."

    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _enable_imap(monkeypatch)
        result = await email_tools.email_inbox()
        assert "Recent emails (last 3 of 3 total)" in result
        assert "From: a@b.com" in result
        assert "Subject: Hi" in result
        client.logout.assert_awaited_once()

    async def test_search_not_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_imap(monkeypatch, search=("NO", []))
        result = await email_tools.email_inbox()
        assert result == "[error] Failed to search inbox."

    async def test_no_message_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_imap(monkeypatch, search=("OK", []))
        result = await email_tools.email_inbox()
        assert result == "Recent emails (last 0 of 0 total):\n"

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

    async def test_login_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _enable_imap(monkeypatch, login_error=RuntimeError("auth denied"))
        result = await email_tools.email_inbox()
        assert result == "[error] Failed to read inbox: auth denied"
        client.logout.assert_awaited_once()


class TestEmailConfigStatus:
    def test_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(email_tools, "_get_config", lambda: _config())
        monkeypatch.setattr(email_tools, "_AIOSMTP_AVAILABLE", False)
        monkeypatch.setattr(email_tools, "_AIOIMAP_AVAILABLE", False)
        result = email_tools.email_config_status()
        assert "SMTP: not configured" in result
        assert "IMAP: not configured" in result
        assert "SMTP lib: not installed" in result
        assert "IMAP lib: not installed" in result

    def test_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            email_tools,
            "_get_config",
            lambda: _config(smtp_host="smtp.example.com", imap_host="imap.example.com"),
        )
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
