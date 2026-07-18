from __future__ import annotations

from typing import Any

import pytest

from raven.core.auth.oauth import (
    OAuthFlow,
    OAuthProvider,
    generate_pkce_pair,
    generate_state,
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


class TestRedirectUri:
    def test_exact_match(self):
        assert validate_redirect_uri("http://localhost:5173/oauth/callback") is True

    def test_subpath_rejected(self):
        assert validate_redirect_uri("http://localhost:5173/oauth/callback/evil") is False

    def test_evil_host_rejected(self):
        assert validate_redirect_uri("http://evil.com/oauth/callback") is False

    def test_empty_rejected(self):
        assert validate_redirect_uri("") is False


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
