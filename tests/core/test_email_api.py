from __future__ import annotations

from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import raven.core.email_api as email_api
from raven.core.email_api import create_email_router

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


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(create_email_router())
    return TestClient(app)


def _raw_email(from_addr: str = "a@b.com", subject: str = "Hi", body: str = "Body") -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg.set_content(body)
    return msg.as_bytes()


def _imap_client(
    monkeypatch: pytest.MonkeyPatch,
    search: tuple[str, list[bytes]] = ("OK", [b"1 2"]),
    fetch: tuple[str, object] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.wait_hello_from_server = AsyncMock()
    client.login = AsyncMock()
    client.select = AsyncMock()
    client.search = AsyncMock(return_value=search)
    client.fetch = AsyncMock(return_value=fetch or ("OK", [(b"1", _raw_email())]))
    client.logout = AsyncMock()
    monkeypatch.setattr(email_api, "aioimaplib", SimpleNamespace(IMAP4_SSL=MagicMock(return_value=client)), raising=False)
    return client


class TestEmailConfig:
    def test_reports_both_sides(self, client, monkeypatch):
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("EMAIL_SMTP_USER", "sender@test.com")
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.test.com")
        monkeypatch.setenv("EMAIL_IMAP_USER", "reader@test.com")
        monkeypatch.setattr(email_api, "_AIOSMTP_AVAILABLE", True)
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", False)
        data = client.get("/api/email/config").json()
        assert data == {
            "smtp_configured": True,
            "imap_configured": True,
            "smtp_lib_available": True,
            "imap_lib_available": False,
            "smtp_host": "smtp.test.com",
            "imap_host": "imap.test.com",
        }

    def test_unconfigured(self, client):
        data = client.get("/api/email/config").json()
        assert data["smtp_configured"] is False
        assert data["imap_configured"] is False
        assert data["smtp_host"] == ""


class TestEmailSend:
    def test_send_no_smtp_lib(self, client, monkeypatch):
        monkeypatch.setattr(email_api, "_AIOSMTP_AVAILABLE", False)
        resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        assert resp.status_code == 400

    def test_send_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(email_api, "_AIOSMTP_AVAILABLE", True)
        resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "SMTP not configured"

    def test_send_success(self, client, monkeypatch):
        send = AsyncMock()
        monkeypatch.setattr(email_api, "_AIOSMTP_AVAILABLE", True)
        monkeypatch.setattr(email_api, "aiosmtplib", SimpleNamespace(send=send), raising=False)
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("EMAIL_SMTP_PORT", "465")
        monkeypatch.setenv("EMAIL_SMTP_USER", "sender@test.com")
        monkeypatch.setenv("EMAIL_SMTP_PASS", "pass")
        resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "to": "a@b.com", "subject": "hi"}
        call = send.await_args
        assert call is not None
        assert call.kwargs["hostname"] == "smtp.test.com"
        assert call.kwargs["port"] == 465
        assert call.kwargs["use_tls"] is True

    def test_send_failure_is_a_500(self, client, monkeypatch):
        monkeypatch.setattr(email_api, "_AIOSMTP_AVAILABLE", True)
        monkeypatch.setattr(
            email_api, "aiosmtplib", SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("refused"))), raising=False
        )
        monkeypatch.setenv("EMAIL_SMTP_HOST", "smtp.test.com")
        monkeypatch.setenv("EMAIL_SMTP_USER", "sender@test.com")
        resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        assert resp.status_code == 500


class TestEmailInbox:
    def test_inbox_no_lib(self, client, monkeypatch):
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", False)
        assert client.get("/api/email/inbox").status_code == 400

    def test_inbox_not_configured(self, client, monkeypatch):
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", True)
        resp = client.get("/api/email/inbox")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "IMAP not configured"

    def test_inbox_lists_recent(self, client, monkeypatch):
        imap = _imap_client(monkeypatch)
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", True)
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.test.com")
        monkeypatch.setenv("EMAIL_IMAP_USER", "reader@test.com")
        monkeypatch.setenv("EMAIL_INBOX_FOLDER", "Agent mail")
        resp = client.get("/api/email/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["emails"][0]["from"] == "a@b.com"
        assert data["emails"][0]["subject"] == "Hi"
        assert "Body" in data["emails"][0]["body_preview"]
        imap.select.assert_awaited_once_with("Agent mail")
        imap.logout.assert_awaited_once()

    def test_inbox_search_failure_returns_empty(self, client, monkeypatch):
        imap = _imap_client(monkeypatch, search=("NO", []))
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", True)
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.test.com")
        monkeypatch.setenv("EMAIL_IMAP_USER", "reader@test.com")
        resp = client.get("/api/email/inbox")
        assert resp.status_code == 200
        assert resp.json() == {"emails": [], "total": 0}
        imap.logout.assert_awaited_once()

    def test_inbox_limit_clamped(self, client, monkeypatch):
        ids = b" ".join(str(i).encode() for i in range(1, 11))
        imap = _imap_client(monkeypatch, search=("OK", [ids]))
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", True)
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.test.com")
        monkeypatch.setenv("EMAIL_IMAP_USER", "reader@test.com")
        resp = client.get("/api/email/inbox?limit=0")
        assert resp.status_code == 200
        assert len(resp.json()["emails"]) == 1
        assert imap.fetch.await_count == 1

    def test_inbox_skips_unfetchable(self, client, monkeypatch):
        _imap_client(monkeypatch, fetch=("NO", []))
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", True)
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.test.com")
        monkeypatch.setenv("EMAIL_IMAP_USER", "reader@test.com")
        data = client.get("/api/email/inbox").json()
        assert data["total"] == 2
        assert data["emails"] == []

    def test_inbox_login_failure_logs_out_once(self, client, monkeypatch):
        imap = _imap_client(monkeypatch)
        imap.login = AsyncMock(side_effect=RuntimeError("auth denied"))
        monkeypatch.setattr(email_api, "_AIOIMAP_AVAILABLE", True)
        monkeypatch.setenv("EMAIL_IMAP_HOST", "imap.test.com")
        monkeypatch.setenv("EMAIL_IMAP_USER", "reader@test.com")
        assert client.get("/api/email/inbox").status_code == 500
        imap.logout.assert_awaited_once()
