from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from raven.core.auth.oauth import (
    _SESSIONS,
    OAuthFlow,
    OAuthProvider,
    OAuthSession,
    _cleanup_sessions,
    generate_pkce_pair,
    generate_state,
    get_authorize_url,
    get_enabled_providers,
    handle_callback,
    register_providers,
    validate_redirect_uri,
)


class MockProvider(OAuthProvider):
    def __init__(self):
        super().__init__(
            name="mock",
            client_id="test_client",
            client_secret="test_secret",
            authorize_url="https://provider.com/oauth/authorize",
            token_url="https://provider.com/oauth/token",
            userinfo_url="https://provider.com/userinfo",
            scopes=["openid", "email"],
            redirect_uri="http://localhost:5173/oauth/callback",
        )

    async def exchange_code(self, code: str, code_verifier: str = "") -> dict[str, Any]:
        return {"access_token": "test_token", "refresh_token": "refresh", "expires_in": 3600}


class MockSession:
    def __init__(self):
        self._data = {}

    async def get(self, key: str) -> Any:
        return self._data.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class TestState:
    def test_state_length(self):
        state = generate_state()
        assert len(state) >= 22

    def test_state_unique(self):
        s1 = generate_state()
        s2 = generate_state()
        assert s1 != s2


class TestRedirectUri:
    def test_exact_match(self):
        assert validate_redirect_uri("http://localhost:5173/oauth/callback") is True

    def test_exact_match_3000(self):
        assert validate_redirect_uri("http://localhost:3000/oauth/callback") is True

    def test_subpath_rejected(self):
        assert validate_redirect_uri("http://localhost:5173/oauth/callback/evil") is False

    def test_evil_host_rejected(self):
        assert validate_redirect_uri("http://evil.com/oauth/callback") is False

    def test_empty_rejected(self):
        assert validate_redirect_uri("") is False

    def test_non_http_rejected(self):
        assert validate_redirect_uri("ftp://localhost/oauth/callback") is False

    def test_trailing_slash_normalized(self):
        assert validate_redirect_uri("http://localhost:5173/oauth/callback/") is True


class TestPkce:
    def test_pkce_pair_length(self):
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) >= 43
        assert len(challenge) == 43

    def test_pkce_pair_not_equal(self):
        verifier, challenge = generate_pkce_pair()
        assert verifier != challenge

    def test_pkce_deterministic(self):
        v1, c1 = generate_pkce_pair()
        v2, c2 = generate_pkce_pair()
        assert v1 != v2
        assert c1 != c2

    def test_challenge_is_base64url(self):
        _, challenge = generate_pkce_pair()
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in challenge)


class TestRegisterProviders:
    @patch("raven.core.auth.oauth.settings")
    def test_register_providers(self, mock_settings):
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        providers = get_enabled_providers()
        assert len(providers) == 3
        names = [p["name"] for p in providers]
        assert "google" in names
        assert "github" in names
        assert "microsoft" in names

    @patch("raven.core.auth.oauth.settings")
    def test_provider_enabled_when_creds_present(self, mock_settings):
        mock_settings.oauth_google_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        providers = get_enabled_providers()
        google = next(p for p in providers if p["name"] == "google")
        assert google["enabled"] is True


class TestGetAuthorizeUrl:
    @patch("raven.core.auth.oauth.settings")
    def test_disabled_provider_returns_none(self, mock_settings):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        result = get_authorize_url("google", "http://localhost:5173/oauth/callback")
        assert result is None

    @patch("raven.core.auth.oauth.settings")
    def test_invalid_redirect_returns_none(self, mock_settings):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        result = get_authorize_url("github", "http://evil.com/callback")
        assert result is None

    @patch("raven.core.auth.oauth.settings")
    def test_unknown_provider_returns_none(self, mock_settings):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        result = get_authorize_url("nonexistent", "http://localhost:5173/oauth/callback")
        assert result is None

    @patch("raven.core.auth.oauth.settings")
    def test_enabled_provider_returns_url(self, mock_settings):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        result = get_authorize_url("github", "http://localhost:5173/oauth/callback")
        assert result is not None
        assert "github.com" in result
        assert "code_challenge" in result
        assert "code_challenge_method=S256" in result


class TestHandleCallback:
    @patch("raven.core.auth.oauth.settings")
    async def test_empty_state_returns_none(self, mock_settings):
        result = await handle_callback("github", "code", "")
        assert result is None

    @patch("raven.core.auth.oauth.settings")
    async def test_invalid_state_returns_none(self, mock_settings):
        result = await handle_callback("github", "code", "nonexistent_state")
        assert result is None

    @patch("raven.core.auth.oauth.settings")
    async def test_state_mismatch_returns_none(self, mock_settings):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        state = generate_state()
        _SESSIONS[state] = OAuthSession(
            state=state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        result = await handle_callback("google", "code", state)
        assert result is None
        _SESSIONS.pop(state, None)

    @patch("raven.core.auth.oauth._fetch_userinfo")
    @patch("raven.core.auth.oauth._exchange_code")
    @patch("raven.core.auth.oauth.settings")
    async def test_successful_callback(self, mock_settings, mock_exchange, mock_fetch):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        state = generate_state()
        _SESSIONS[state] = OAuthSession(
            state=state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        mock_exchange.return_value = {"access_token": "gh_token"}
        mock_fetch.return_value = {"login": "testuser", "id": "123"}
        result = await handle_callback("github", "auth_code", state)
        assert result is not None
        assert result["provider"] == "github"
        assert result["email"] == "testuser@oauth"
        assert "access_token" in result
        assert state not in _SESSIONS

    @patch("raven.core.auth.oauth._exchange_code")
    @patch("raven.core.auth.oauth.settings")
    async def test_exchange_failure_returns_none(self, mock_settings, mock_exchange):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        state = generate_state()
        _SESSIONS[state] = OAuthSession(
            state=state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        mock_exchange.return_value = None
        result = await handle_callback("github", "bad_code", state)
        assert result is None

    @patch("raven.core.auth.oauth._fetch_userinfo")
    @patch("raven.core.auth.oauth._exchange_code")
    @patch("raven.core.auth.oauth.settings")
    async def test_no_access_token_returns_none(self, mock_settings, mock_exchange, mock_fetch):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        state = generate_state()
        _SESSIONS[state] = OAuthSession(
            state=state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        mock_exchange.return_value = {"error": "bad_code"}
        result = await handle_callback("github", "code", state)
        assert result is None

    @patch("raven.core.auth.oauth._fetch_userinfo")
    @patch("raven.core.auth.oauth._exchange_code")
    @patch("raven.core.auth.oauth.settings")
    async def test_fetch_userinfo_failure_returns_none(self, mock_settings, mock_exchange, mock_fetch):
        mock_settings.oauth_redirect_base = "http://localhost:5173"
        mock_settings.oauth_github_client_id.get_secret_value.return_value = "id"
        mock_settings.oauth_github_client_secret.get_secret_value.return_value = "secret"
        mock_settings.oauth_google_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_google_client_secret.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_id.get_secret_value.return_value = ""
        mock_settings.oauth_microsoft_client_secret.get_secret_value.return_value = ""
        register_providers()
        state = generate_state()
        _SESSIONS[state] = OAuthSession(
            state=state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        mock_exchange.return_value = {"access_token": "token"}
        mock_fetch.return_value = None
        result = await handle_callback("github", "code", state)
        assert result is None


class TestCleanupSessions:
    def test_cleanup_removes_expired(self):
        old_state = "old_session"
        _SESSIONS[old_state] = OAuthSession(
            state=old_state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        _SESSIONS[old_state].created_at = time.time() - 9999
        _cleanup_sessions()
        assert old_state not in _SESSIONS

    def test_cleanup_keeps_fresh(self):
        fresh_state = "fresh_session"
        _SESSIONS[fresh_state] = OAuthSession(
            state=fresh_state, provider="github", redirect_uri="http://localhost:5173/oauth/callback"
        )
        _cleanup_sessions()
        assert fresh_state in _SESSIONS
        _SESSIONS.pop(fresh_state, None)


@pytest.mark.asyncio
async def test_oauth_flow_with_pkce():
    session = MockSession()
    flow = OAuthFlow(MockProvider())

    result = await flow.initiate(session)
    assert "auth_url" in result
    assert "code_challenge_method=S256" in result["auth_url"]

    stored_state = await session.get("oauth_state")
    assert stored_state is not None
    assert stored_state in result["auth_url"]

    token = await flow.handle_callback(code="auth_code", state=stored_state, session=session)
    assert token.access_token == "test_token"
    assert token.refresh_token == "refresh"

    assert await session.get("oauth_state") is None
    assert await session.get("pkce_verifier") is None


@pytest.mark.asyncio
async def test_oauth_flow_invalid_state_rejected():
    session = MockSession()
    flow = OAuthFlow(MockProvider())

    await flow.initiate(session)

    with pytest.raises(ValueError, match="Invalid state parameter"):
        await flow.handle_callback(code="auth_code", state="wrong_state", session=session)


@pytest.mark.asyncio
async def test_oauth_flow_missing_pkce_verifier():
    session = MockSession()
    flow = OAuthFlow(MockProvider())

    await flow.initiate(session)
    state = await session.get("oauth_state")
    await session.delete("pkce_verifier")

    with pytest.raises(ValueError, match="PKCE verifier not found"):
        await flow.handle_callback(code="auth_code", state=state, session=session)


class TestOAuthSession:
    def test_defaults(self):
        s = OAuthSession(state="s", provider="p", redirect_uri="r")
        assert s.code_verifier == ""
        assert s.user_info is None
        assert s.created_at > 0


class TestOAuthProvider:
    def test_defaults(self):
        p = OAuthProvider(
            name="test", client_id="id", client_secret="secret",
            authorize_url="a", token_url="t", userinfo_url="u", scopes=[]
        )
        assert p.redirect_uri == ""
        assert p.icon == ""
        assert p.enabled is False
