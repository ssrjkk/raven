from __future__ import annotations

import asyncio
import dataclasses
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import raven.channels.email.channel as email_channel_mod
from raven.channels.email.channel import POLL_BATCH, EmailChannel, address_for_session, session_id_for
from raven.core.email_config import EmailConfig
from raven.core.models import Message

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

CONFIGURED = EmailConfig(
    smtp_host="smtp.test.com",
    smtp_user="bot@test.com",
    smtp_pass="smp",
    imap_host="imap.test.com",
    imap_user="bot@test.com",
    imap_pass="imp",
    poll_interval=1,
)


@pytest.fixture(autouse=True)
def _clean_email_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _EMAIL_ENV:
        monkeypatch.delenv(name, raising=False)


def _raw_email(from_header: str = "Alice <alice@corp.com>", subject: str = "Question", body: str = "Please help") -> bytes:
    msg = EmailMessage()
    msg["From"] = from_header
    msg["Subject"] = subject
    msg.set_content(body)
    return msg.as_bytes()


def _multipart_email() -> bytes:
    msg = EmailMessage()
    msg["From"] = "alice@corp.com"
    msg["Subject"] = "Mixed"
    msg.set_content("plain part")
    msg.add_alternative("<p>html part</p>", subtype="html")
    return msg.as_bytes()


def _imap(
    monkeypatch: pytest.MonkeyPatch,
    search: tuple[str, list[bytes]] = ("OK", [b"1"]),
    fetch: tuple[str, object] = ("OK", [(b"1", _raw_email())]),
) -> MagicMock:
    client = MagicMock()
    client.wait_hello_from_server = AsyncMock()
    client.login = AsyncMock()
    client.select = AsyncMock()
    client.search = AsyncMock(return_value=search)
    client.fetch = AsyncMock(return_value=fetch)
    client.store = AsyncMock()
    client.logout = AsyncMock()
    monkeypatch.setattr(email_channel_mod, "_AIOIMAP_AVAILABLE", True)
    monkeypatch.setattr(
        email_channel_mod, "aioimaplib", SimpleNamespace(IMAP4_SSL=MagicMock(return_value=client)), raising=False
    )
    return client


def _smtp(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    send = AsyncMock()
    monkeypatch.setattr(email_channel_mod, "_AIOSMTP_AVAILABLE", True)
    monkeypatch.setattr(email_channel_mod, "aiosmtplib", SimpleNamespace(send=send), raising=False)
    return send


def _channel(client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> EmailChannel:
    channel = EmailChannel(config=CONFIGURED)
    channel._imap_client = client
    channel._ready = True
    return channel


def test_session_id_round_trip():
    sid = session_id_for("alice@corp.com")
    assert sid == "email:alice@corp.com:default"
    assert address_for_session(sid) == "alice@corp.com"


def test_address_for_session_rejects_other_channels():
    assert address_for_session("telegram:42:default") == ""
    assert address_for_session("email:") == ""


@pytest.mark.asyncio
async def test_connect_skipped_without_library(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(email_channel_mod, "_AIOIMAP_AVAILABLE", False)
    channel = EmailChannel(config=CONFIGURED)
    await channel.connect()
    assert await channel.health_check() is False


@pytest.mark.asyncio
async def test_connect_skipped_when_unconfigured(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    channel = EmailChannel()
    await channel.connect()
    assert await channel.health_check() is False
    client.login.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_selects_configured_folder(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    channel = EmailChannel(config=dataclasses.replace(CONFIGURED, inbox_folder="Agent mail"))
    await channel.connect()
    assert await channel.health_check() is True
    client.login.assert_awaited_once_with("bot@test.com", "imp")
    client.select.assert_awaited_once_with("Agent mail")


@pytest.mark.asyncio
async def test_connect_failure_leaves_channel_down(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    client.login = AsyncMock(side_effect=RuntimeError("BADLOGIN"))
    channel = EmailChannel(config=CONFIGURED)
    await channel.connect()
    assert await channel.health_check() is False


@pytest.mark.asyncio
async def test_disconnect_logs_out_once(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    channel = _channel(client, monkeypatch)
    await channel.disconnect()
    client.logout.assert_awaited_once()
    assert channel._imap_client is None


@pytest.mark.asyncio
async def test_send_replies_to_the_session_address(monkeypatch: pytest.MonkeyPatch):
    send = _smtp(monkeypatch)
    channel = EmailChannel(config=CONFIGURED)
    await channel.send(session_id_for("alice@corp.com"), Message(session_id="x", channel="email", role="assistant", content="hi"))
    call = send.await_args
    assert call is not None
    assert call.kwargs["hostname"] == "smtp.test.com"
    assert call.kwargs["start_tls"] is True
    assert call.args[0]["To"] == "alice@corp.com"


@pytest.mark.asyncio
async def test_send_without_recipient_address_is_dropped(monkeypatch: pytest.MonkeyPatch):
    send = _smtp(monkeypatch)
    channel = EmailChannel(config=CONFIGURED)
    await channel.send("telegram:42:default", Message(session_id="x", channel="email", role="assistant", content="hi"))
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_requires_smtp(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(email_channel_mod, "_AIOSMTP_AVAILABLE", False)
    channel = EmailChannel(config=CONFIGURED)
    await channel.send(session_id_for("a@b.com"), Message(session_id="x", channel="email", role="assistant", content="hi"))

    send = _smtp(monkeypatch)
    unconfigured = EmailChannel(config=EmailConfig(imap_host="imap.test.com", imap_user="bot@test.com"))
    await unconfigured.send(session_id_for("a@b.com"), Message(session_id="x", channel="email", role="assistant", content="hi"))
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_failure_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch):
    _smtp(monkeypatch)
    monkeypatch.setattr(
        email_channel_mod,
        "aiosmtplib",
        SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("refused"))),
        raising=False,
    )
    channel = EmailChannel(config=CONFIGURED)
    await channel.send(session_id_for("a@b.com"), Message(session_id="x", channel="email", role="assistant", content="hi"))


@pytest.mark.asyncio
async def test_check_inbox_without_client_or_handler(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    channel = _channel(client, monkeypatch)
    await channel._check_inbox()
    client.search.assert_not_awaited()

    await channel.on_message(AsyncMock())
    channel._imap_client = None
    await channel._check_inbox()
    client.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_inbox_search_failure_stops(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, search=("NO", []))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._check_inbox()
    client.fetch.assert_not_awaited()
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_inbox_caps_batch_size(monkeypatch: pytest.MonkeyPatch):
    ids = b" ".join(str(i).encode() for i in range(1, 12))
    client = _imap(monkeypatch, search=("OK", [ids]))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._check_inbox()
    assert client.fetch.await_count == POLL_BATCH
    assert client.fetch.await_args_list[0][0][0] == b"7"


@pytest.mark.asyncio
async def test_handles_one_dispatches_parsed_message(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    order: list[str] = []
    client.store = AsyncMock(side_effect=lambda *a: order.append("store"))
    handler = AsyncMock(side_effect=lambda m: order.append("dispatch"))
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)

    await channel._handle_one(b"1")

    assert order == ["store", "dispatch"]
    event = handler.await_args_list[0].args[0]
    assert event.channel == "email"
    assert event.session_id == "email:alice@corp.com:default"
    assert event.user_id == "alice@corp.com"
    assert event.text == "Please help"
    assert event.metadata == {"subject": "Question"}


@pytest.mark.asyncio
async def test_handles_one_reads_the_plain_multipart_part(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, fetch=("OK", [(b"1", _multipart_email())]))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._handle_one(b"1")
    assert handler.await_args_list[0].args[0].text == "plain part"


@pytest.mark.asyncio
async def test_handles_one_skips_empty_bodies(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, fetch=("OK", [(b"1", _raw_email(body="   \n  "))]))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._handle_one(b"1")
    handler.assert_not_awaited()
    client.store.assert_awaited_once_with("1", "+FLAGS", "\\Seen")


@pytest.mark.asyncio
async def test_handles_one_skips_display_name_without_address(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, fetch=("OK", [(b"1", _raw_email(from_header="Undisclosed"))]))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._handle_one(b"1")
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_handles_one_survives_unparseable_message(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, fetch=("OK", [(b"1", b"\xff\xfe not a message")]))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._handle_one(b"1")
    client.store.assert_awaited_once()
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_handles_one_ignores_failed_fetch(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, fetch=("NO", []))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._handle_one(b"1")
    client.store.assert_not_awaited()
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_store_failure_still_dispatches(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    client.store = AsyncMock(side_effect=RuntimeError("server refused"))
    handler = AsyncMock()
    channel = _channel(client, monkeypatch)
    await channel.on_message(handler)
    await channel._handle_one(b"1")
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_polls_then_stop_cancels(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch, search=("OK", []))
    channel = _channel(client, monkeypatch)
    await channel.on_message(AsyncMock())
    await channel.start()
    assert channel._poll_task is not None
    await asyncio.sleep(0.05)
    assert client.search.await_count >= 1
    await channel.stop()
    assert channel._poll_task is None
    assert await channel.health_check() is False


@pytest.mark.asyncio
async def test_start_without_connection_does_not_poll(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(email_channel_mod, "_AIOIMAP_AVAILABLE", False)
    channel = EmailChannel()
    await channel.start()
    assert channel._poll_task is None


@pytest.mark.asyncio
async def test_poll_loop_keeps_running_after_an_error(monkeypatch: pytest.MonkeyPatch):
    client = _imap(monkeypatch)
    client.search = AsyncMock(side_effect=RuntimeError("socket closed"))
    channel = _channel(client, monkeypatch)
    await channel.on_message(AsyncMock())
    await channel.start()
    await asyncio.sleep(0.05)
    assert channel._poll_task is not None
    assert not channel._poll_task.cancelled()
    await channel.stop()
