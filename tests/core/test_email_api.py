from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raven.core.email_api import create_email_router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(create_email_router())
    return TestClient(app)


class TestEmailConfig:
    def test_config_endpoint(self, client):
        with patch("raven.core.email_api._get_config", return_value={
            "smtp_host": "smtp.test.com",
            "imap_host": "imap.test.com",
        }):
            resp = client.get("/api/email/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["smtp_configured"] is True
        assert data["imap_configured"] is True


class TestEmailSend:
    def test_send_no_smtp_lib(self, client):
        with patch("raven.core.email_api._AIOSMTP_AVAILABLE", False):
            resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        assert resp.status_code == 400

    def test_send_not_configured(self, client):
        with patch("raven.core.email_api._AIOSMTP_AVAILABLE", True):
            with patch("raven.core.email_api._get_config", return_value={}):
                resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        assert resp.status_code == 400

    def test_send_success(self, client):
        import raven.core.email_api as email_mod
        mock_aiosmtplib = MagicMock()
        mock_aiosmtplib.send = AsyncMock()
        patcher = patch.object(email_mod, "aiosmtplib", mock_aiosmtplib, create=True)
        patcher.start()
        try:
            with patch("raven.core.email_api._AIOSMTP_AVAILABLE", True):
                with patch("raven.core.email_api._get_config", return_value={
                    "smtp_host": "smtp.test.com",
                    "smtp_port": "587",
                    "smtp_user": "user@test.com",
                    "smtp_pass": "pass",
                }):
                    resp = client.post("/api/email/send", json={"to": "a@b.com", "subject": "hi", "body": "test"})
        finally:
            patcher.stop()
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestEmailInbox:
    def test_inbox_no_lib(self, client):
        with patch("raven.core.email_api._AIOIMAP_AVAILABLE", False):
            resp = client.get("/api/email/inbox")
        assert resp.status_code == 400

    def test_inbox_not_configured(self, client):
        with patch("raven.core.email_api._AIOIMAP_AVAILABLE", True):
            with patch("raven.core.email_api._get_config", return_value={}):
                resp = client.get("/api/email/inbox")
        assert resp.status_code == 400

    def test_inbox_success(self, client):
        import raven.core.email_api as email_mod

        mock_client = AsyncMock()
        mock_client.wait_hello_from_server = AsyncMock()
        mock_client.login = AsyncMock()
        mock_client.select = AsyncMock()
        mock_client.search = AsyncMock(return_value=("OK", [b"1 2"]))
        mock_client.fetch = AsyncMock(return_value=("OK", [(b"1", b"From: test@test.com\r\nSubject: Hi\r\n\r\nBody")]))
        mock_client.logout = AsyncMock()

        mock_aioimaplib = MagicMock()
        mock_aioimaplib.IMAP4_SSL = MagicMock(return_value=mock_client)

        patcher = patch.object(email_mod, "aioimaplib", mock_aioimaplib, create=True)
        patcher.start()
        try:
            with patch("raven.core.email_api._AIOIMAP_AVAILABLE", True):
                with patch("raven.core.email_api._get_config", return_value={
                    "imap_host": "imap.test.com",
                    "imap_port": "993",
                    "imap_user": "user@test.com",
                    "imap_pass": "pass",
                }):
                    resp = client.get("/api/email/inbox")
        finally:
            patcher.stop()
        assert resp.status_code == 200
        data = resp.json()
        assert "emails" in data
