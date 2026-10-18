from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json as json_mod
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.config import SafeSecretStr
from raven.core.webhooks import create_webhook_router


class FakeHeaders(dict[str, str]):
    """Starlette headers match any casing, and uvicorn lowercases the ASGI scope before they are built
    (h11_impl does ``key.lower()``), so a plain dict that keeps the caller's casing models neither."""

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key.lower(), default)


class FakeAppState:
    pass


class FakeRequest:
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        app_state: FakeAppState | None = None,
        body_bytes: bytes | None = None,
        query_params: dict[str, str] | None = None,
    ) -> None:
        self.headers = FakeHeaders({k.lower(): v for k, v in (headers or {}).items()})
        self.app = MagicMock()
        self.app.state = app_state or FakeAppState()
        self.query_params = query_params or {}
        self._body_bytes = body_bytes or b"{}"

    async def body(self) -> bytes:
        return self._body_bytes


@pytest.fixture(autouse=True)
def _clean_webhook_env(monkeypatch):
    """These routes read platform secrets straight from the environment, so a developer's own .env
    must not decide whether a test sees a configured or an unconfigured platform."""
    for var in (
        "SLACK_SIGNING_SECRET",
        "GITHUB_TOKEN",
        "GITHUB_WEBHOOK_SECRET",
        "GITLAB_WEBHOOK_SECRET",
        "LINE_CHANNEL_SECRET",
        "FEISHU_ENCRYPT_KEY",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_VERIFY_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)


class FakeDB:
    async def health_check(self) -> bool:
        return True


class RecordingChannel:
    """The adapter entry points differ in arity (LINE takes a body only), so accept whatever the route passes."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def handle_webhook(self, *args: Any) -> bool:
        self.calls.append(args)
        return True


def _state_with(channel: str, instance: object) -> FakeAppState:
    state = FakeAppState()
    setattr(state, f"{channel}_channel", instance)
    return state


def _hub_signature(secret: str, body_bytes: bytes) -> str:
    return "sha256=" + hmac_mod.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


def _line_signature(secret: str, body_bytes: bytes) -> str:
    digest = hmac_mod.new(secret.encode(), body_bytes, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _lark_signature(encrypt_key: str, timestamp: str, nonce: str, body_bytes: bytes) -> str:
    seed = f"{timestamp}{nonce}{encrypt_key}".encode() + body_bytes
    return hashlib.sha256(seed).hexdigest()


async def _dispatch(router: Any, index: int, body: dict[str, Any], req: FakeRequest) -> Any:
    """Call the endpoint the way FastAPI's router would, so the tests exercise the handler and not HTTP plumbing."""
    return await router.routes[index].endpoint(body, req)


async def _dispatch_get(router: Any, index: int, req: FakeRequest) -> Any:
    return await router.routes[index].endpoint(req)


@pytest.mark.asyncio
async def test_generic_webhook_text_field():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"text": "hello"}
    body_bytes = json_mod.dumps(body).encode()
    import hashlib
    import hmac as hmac_mod
    sig = "sha256=" + hmac_mod.new(b"test-secret", body_bytes, hashlib.sha256).hexdigest()
    req = FakeRequest(headers={"X-Webhook-Source": "github", "X-Webhook-Signature": sig}, body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        resp = await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True
    handler.assert_awaited_once()
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "webhook"
    assert "hello" in event.text
    assert "<<<EXTERNAL_UNTRUSTED_CONTENT>>>" in event.text


@pytest.mark.asyncio
async def test_generic_webhook_message_field():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"message": "world"}
    body_bytes = json_mod.dumps(body).encode()
    import hashlib
    import hmac as hmac_mod
    sig = "sha256=" + hmac_mod.new(b"test-secret", body_bytes, hashlib.sha256).hexdigest()
    req = FakeRequest(headers={"X-Webhook-Source": "test", "X-Webhook-Signature": sig}, body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        resp = await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True
    event = handler.await_args[0][0]  # type: ignore[index]
    assert "world" in event.text
    assert "<<<EXTERNAL_UNTRUSTED_CONTENT>>>" in event.text


@pytest.mark.asyncio
async def test_generic_webhook_no_text():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"not_text": ""}
    body_bytes = json_mod.dumps(body).encode()
    import hashlib
    import hmac as hmac_mod
    sig = "sha256=" + hmac_mod.new(b"test-secret", body_bytes, hashlib.sha256).hexdigest()
    req = FakeRequest(headers={"X-Webhook-Signature": sig}, body_bytes=body_bytes)
    from fastapi import HTTPException

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        with pytest.raises(HTTPException) as exc:
            await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_slack_url_verification():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "url_verification", "challenge": "abc123"}
    body_bytes = json_mod.dumps(body).encode()
    ts = str(int(time.time()))
    import hashlib
    import hmac as hmac_mod
    sig_basestring = f"v0:{ts}:{body_bytes.decode('utf-8')}"
    slack_sig = "v0=" + hmac_mod.new(b"test-secret", sig_basestring.encode(), hashlib.sha256).hexdigest()
    req = FakeRequest(
        headers={"X-Slack-Signature": slack_sig, "X-Slack-Request-Timestamp": ts},
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        resp = await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp == {"challenge": "abc123"}


@pytest.mark.asyncio
async def test_slack_events_no_channel():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "event_callback", "event": {"type": "message", "user": "U1", "text": "hi", "channel": "C1"}}
    body_bytes = json_mod.dumps(body).encode()
    ts = str(int(time.time()))
    import hashlib
    import hmac as hmac_mod
    sig_basestring = f"v0:{ts}:{body_bytes.decode('utf-8')}"
    slack_sig = "v0=" + hmac_mod.new(b"test-secret", sig_basestring.encode(), hashlib.sha256).hexdigest()
    req = FakeRequest(
        headers={"X-Slack-Signature": slack_sig, "X-Slack-Request-Timestamp": ts},
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        resp = await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True


@pytest.mark.asyncio
async def test_whatsapp_verify():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    req = FakeRequest()
    req.query_params = {"hub.mode": "subscribe", "hub.verify_token": "wrong_token", "hub.challenge": "123"}
    with pytest.raises(Exception):
        await router.routes[3].endpoint(req)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_slack_events_uses_channel_signing_secret(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "env-slack-secret")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "event_callback", "event": {"type": "message", "user": "U1", "text": "hi", "channel": "C1"}}
    body_bytes = json_mod.dumps(body).encode()
    ts = str(int(time.time()))
    import hashlib
    import hmac as hmac_mod

    sig_basestring = f"v0:{ts}:{body_bytes.decode('utf-8')}"
    good_sig = "v0=" + hmac_mod.new(b"env-slack-secret", sig_basestring.encode(), hashlib.sha256).hexdigest()
    req = FakeRequest(
        headers={"X-Slack-Signature": good_sig, "X-Slack-Request-Timestamp": ts},
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        resp = await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert resp["ok"] is True


@pytest.mark.asyncio
async def test_slack_events_rejects_bad_signature_with_env_secret(monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "env-slack-secret")
    from fastapi import HTTPException

    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "event_callback", "event": {"type": "message"}}
    ts = str(int(time.time()))
    req = FakeRequest(
        headers={"X-Slack-Signature": "v0=" + "0" * 64, "X-Slack-Request-Timestamp": ts},
        body_bytes=json_mod.dumps(body).encode(),
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        with pytest.raises(HTTPException) as exc_info:
            await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_generic_webhook_fails_closed_without_secret():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"text": "hello"}
    req = FakeRequest(headers={"X-Webhook-Source": "github"}, body_bytes=json_mod.dumps(body).encode())
    from fastapi import HTTPException

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        with pytest.raises(HTTPException) as exc_info:
            await router.routes[0].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 403
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_whatsapp_fails_closed_without_secret():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body: dict[str, Any] = {"entry": []}
    req = FakeRequest(body_bytes=json_mod.dumps(body).encode())
    from fastapi import HTTPException

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        with pytest.raises(HTTPException) as exc_info:
            await router.routes[2].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_googlechat_fails_closed_without_secret():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"message": "x"}
    req = FakeRequest(body_bytes=json_mod.dumps(body).encode())
    from fastapi import HTTPException

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        with pytest.raises(HTTPException) as exc_info:
            await router.routes[4].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_slack_events_fails_closed_when_no_secret_anywhere():
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body = {"type": "event_callback", "event": {"type": "message"}}
    req = FakeRequest(body_bytes=json_mod.dumps(body).encode())
    from fastapi import HTTPException

    with patch("raven.core.webhooks.settings") as mock_settings, patch(
        "raven.core.webhooks.get_channel_config", return_value={}
    ):
        mock_settings.web_secret_key = SafeSecretStr("")
        with pytest.raises(HTTPException) as exc_info:
            await router.routes[1].endpoint(body, req)  # type: ignore[attr-defined]
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_github_webhook_accepts_hub_signature(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "hub-secret")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "o/r"},
        "commits": [{"message": "close the webhook hole"}],
    }
    body_bytes = json_mod.dumps(body).encode()
    req = FakeRequest(
        headers={
            "X-Hub-Signature-256": _hub_signature("hub-secret", body_bytes),
            "X-GitHub-Event": "push",
        },
        app_state=_state_with("github", ch),
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        resp = await _dispatch(router, 9, body, req)
    assert resp == {"ok": True}
    assert ch.calls[0][0] == body
    assert ch.calls[0][1]["x-github-event"] == "push"


@pytest.mark.asyncio
async def test_github_webhook_rejects_tampered_and_missing_hub_signature(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "hub-secret")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body_bytes = json_mod.dumps({"ref": "refs/heads/main"}).encode()

    forged = FakeRequest(
        headers={"X-Hub-Signature-256": _hub_signature("hub-secret", b"some other payload")},
        app_state=_state_with("github", ch),
        body_bytes=body_bytes,
    )
    anonymous = FakeRequest(app_state=_state_with("github", ch), body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        for req in (forged, anonymous):
            with pytest.raises(HTTPException) as exc_info:
                await _dispatch(router, 9, {"ref": "refs/heads/main"}, req)
            assert exc_info.value.status_code == 403
    assert ch.calls == []


@pytest.mark.asyncio
async def test_github_webhook_without_platform_secret_uses_generic_hmac(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body_bytes = json_mod.dumps({"ref": "refs/heads/main"}).encode()
    req = FakeRequest(
        headers={"X-Webhook-Signature": _hub_signature("test-secret", body_bytes)},
        app_state=_state_with("github", ch),
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        resp = await _dispatch(router, 9, {"ref": "refs/heads/main"}, req)
    assert resp == {"ok": True}
    assert len(ch.calls) == 1


@pytest.mark.asyncio
async def test_github_webhook_reports_an_unconfigured_channel(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "hub-secret")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    body_bytes = json_mod.dumps({}).encode()
    req = FakeRequest(headers={"X-Hub-Signature-256": _hub_signature("hub-secret", body_bytes)}, body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("")
        resp = await _dispatch(router, 9, {}, req)
    assert resp == {"ok": False, "error": "github channel not configured"}


@pytest.mark.asyncio
async def test_gitlab_webhook_checks_shared_token(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "gl-shared-token")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {"object_kind": "push", "project_name": "raven"}
    body_bytes = json_mod.dumps(body).encode()

    def req(token: str) -> FakeRequest:
        return FakeRequest(
            headers={"X-Gitlab-Token": token, "X-Gitlab-Event": "Push Hook"},
            app_state=_state_with("gitlab", ch),
            body_bytes=body_bytes,
        )

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        mock_settings.gitlab_webhook_secret = SafeSecretStr("")
        assert await _dispatch(router, 10, body, req("gl-shared-token")) == {"ok": True}
        for bad in ("wrong", ""):
            with pytest.raises(HTTPException) as exc_info:
                await _dispatch(router, 10, body, req(bad))
            assert exc_info.value.status_code == 403
    assert len(ch.calls) == 1
    assert ch.calls[0][1]["x-gitlab-event"] == "Push Hook"


@pytest.mark.asyncio
async def test_gitlab_webhook_falls_back_to_settings_secret(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("GITLAB_WEBHOOK_SECRET", raising=False)
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {"object_kind": "push"}
    body_bytes = json_mod.dumps(body).encode()
    req = FakeRequest(
        headers={"X-Gitlab-Token": "settings-token"}, app_state=_state_with("gitlab", ch), body_bytes=body_bytes
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        mock_settings.gitlab_webhook_secret = SafeSecretStr("settings-token")
        assert await _dispatch(router, 10, body, req) == {"ok": True}

    # A GitLab token is not the generic HMAC: with no platform secret configured the route demands one.
    anonymous = FakeRequest(headers={"X-Gitlab-Token": "settings-token"}, body_bytes=body_bytes)
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        mock_settings.gitlab_webhook_secret = SafeSecretStr("")
        with pytest.raises(HTTPException) as exc_info:
            await _dispatch(router, 10, body, anonymous)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_line_webhook_checks_base64_signature(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("LINE_CHANNEL_SECRET", "line-secret")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {"events": [{"type": "message", "source": {"userId": "U1"}, "message": {"text": "hi"}}]}
    body_bytes = json_mod.dumps(body).encode()

    def req(sig: str) -> FakeRequest:
        return FakeRequest(
            headers={"X-Line-Signature": sig}, app_state=_state_with("line", ch), body_bytes=body_bytes
        )

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        good = await _dispatch(router, 8, body, req(_line_signature("line-secret", body_bytes)))
        assert good == {"ok": True}
        # LINE signs with base64, not hex — a hex HMAC of the same body must not pass.
        for bad in (_hub_signature("line-secret", body_bytes), "not-a-signature"):
            with pytest.raises(HTTPException) as exc_info:
                await _dispatch(router, 8, body, req(bad))
            assert exc_info.value.status_code == 403
    assert len(ch.calls) == 1


@pytest.mark.asyncio
async def test_line_webhook_without_platform_secret_uses_generic_hmac(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_SECRET", raising=False)
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body: dict[str, Any] = {"events": []}
    body_bytes = json_mod.dumps(body).encode()
    req = FakeRequest(
        headers={"X-Webhook-Signature": _hub_signature("test-secret", body_bytes)},
        app_state=_state_with("line", ch),
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        assert await _dispatch(router, 8, body, req) == {"ok": True}


@pytest.mark.asyncio
async def test_feishu_webhook_checks_sha256_signature(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "lark-key")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {"schema": "2.0", "header": {"event_type": "im.message.receive_v1"}}
    body_bytes = json_mod.dumps(body).encode()
    ts, nonce = str(int(time.time())), "n0nce"

    def req(sig: str) -> FakeRequest:
        return FakeRequest(
            headers={
                "X-Lark-Signature": sig,
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
            },
            app_state=_state_with("feishu", ch),
            body_bytes=body_bytes,
        )

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        assert await _dispatch(router, 7, body, req(_lark_signature("lark-key", ts, nonce, body_bytes))) == {
            "ok": True
        }
        # Feishu's digest is a plain SHA-256 over key + body, so an HMAC of the same key must not pass.
        for bad in (_hub_signature("lark-key", body_bytes), "0" * 64):
            with pytest.raises(HTTPException) as exc_info:
                await _dispatch(router, 7, body, req(bad))
            assert exc_info.value.status_code == 403
    assert len(ch.calls) == 1


@pytest.mark.asyncio
async def test_feishu_webhook_echoes_the_verification_challenge(monkeypatch):
    """Without the echoed challenge the Feishu console never saves the callback URL, so the
    adapter could not receive events even with a correct signature scheme."""
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "lark-key")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {"challenge": "ajls384kdjx98XX", "token": "t", "type": "url_verification"}
    body_bytes = json_mod.dumps(body).encode()
    ts, nonce = str(int(time.time())), "n0nce"
    req = FakeRequest(
        headers={
            "X-Lark-Signature": _lark_signature("lark-key", ts, nonce, body_bytes),
            "X-Lark-Request-Timestamp": ts,
            "X-Lark-Request-Nonce": nonce,
        },
        app_state=_state_with("feishu", ch),
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        assert await _dispatch(router, 7, body, req) == {"challenge": "ajls384kdjx98XX"}
    assert ch.calls == []


@pytest.mark.asyncio
async def test_feishu_webhook_without_encrypt_key_uses_generic_hmac(monkeypatch):
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body: dict[str, Any] = {"header": {}}
    body_bytes = json_mod.dumps(body).encode()
    req = FakeRequest(
        headers={"X-Webhook-Signature": _hub_signature("test-secret", body_bytes)},
        app_state=_state_with("feishu", ch),
        body_bytes=body_bytes,
    )
    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("test-secret")
        assert await _dispatch(router, 7, body, req) == {"ok": True}


@pytest.mark.asyncio
async def test_whatsapp_post_prefers_the_meta_app_secret(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("WHATSAPP_APP_SECRET", "meta-app-secret")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]
    ch = RecordingChannel()
    body = {"entry": [{"changes": [{"field": "messages", "value": {}}]}]}
    body_bytes = json_mod.dumps(body).encode()

    def req(sig: str) -> FakeRequest:
        return FakeRequest(
            headers={"X-Hub-Signature-256": sig}, app_state=_state_with("whatsapp", ch), body_bytes=body_bytes
        )

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("admin-secret")
        assert await _dispatch(router, 2, body, req(_hub_signature("meta-app-secret", body_bytes))) == {"ok": True}
        with pytest.raises(HTTPException) as exc_info:
            await _dispatch(router, 2, body, req(_hub_signature("admin-secret", body_bytes)))
        assert exc_info.value.status_code == 403
    assert len(ch.calls) == 1


@pytest.mark.asyncio
async def test_whatsapp_handshake_keeps_the_admin_secret_out_of_the_query(monkeypatch):
    """hub.verify_token is sent in a URL, which proxies and access logs record — so when a dedicated
    verify token is configured, the gateway's WEB_SECRET_KEY must not answer to it."""
    from fastapi import HTTPException

    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "meta-verify-token")
    db = FakeDB()
    handler = AsyncMock()
    router = create_webhook_router(db, handler)  # type: ignore[arg-type]

    def req(token: str) -> FakeRequest:
        return FakeRequest(
            query_params={"hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": "12345"}
        )

    with patch("raven.core.webhooks.settings") as mock_settings:
        mock_settings.web_secret_key = SafeSecretStr("admin-secret")
        assert await _dispatch_get(router, 3, req("meta-verify-token")) == 12345
        with pytest.raises(HTTPException) as exc_info:
            await _dispatch_get(router, 3, req("admin-secret"))
        assert exc_info.value.status_code == 403

