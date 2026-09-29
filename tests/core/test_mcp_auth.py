from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import Request

from raven.core.mcp.auth import authorize_request


def _req(headers: dict[str, str]) -> MagicMock:
    req = MagicMock(spec=Request)
    req.headers = headers
    return req


def test_no_token_denied() -> None:
    assert authorize_request(_req({})) is False


def test_bearer_token_accepted() -> None:
    with patch("raven.core.mcp.auth.token_manager") as tm:
        tm.validate_token.return_value = {"user_id": "u1", "role": "admin"}
        assert authorize_request(_req({"Authorization": "Bearer tok"})) is True


def test_web_secret_key_accepted() -> None:
    with (
        patch("raven.core.mcp.auth.token_manager") as tm,
        patch("raven.core.mcp.auth.get_settings") as gs,
    ):
        tm.validate_token.return_value = None
        gs.return_value.web_secret_key.get_secret_value.return_value = "secret"
        assert authorize_request(_req({"X-Raven-Key": "secret"})) is True


def test_wrong_key_denied() -> None:
    with (
        patch("raven.core.mcp.auth.token_manager") as tm,
        patch("raven.core.mcp.auth.get_settings") as gs,
    ):
        tm.validate_token.return_value = None
        gs.return_value.web_secret_key.get_secret_value.return_value = "secret"
        assert authorize_request(_req({"X-Raven-Key": "nope"})) is False
