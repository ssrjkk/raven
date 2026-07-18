from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from raven.core.config import settings


@dataclass
class OAuthProvider:
    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: list[str]
    redirect_uri: str = ""
    icon: str = ""
    enabled: bool = False

    async def exchange_code(self, code: str, code_verifier: str = "") -> dict[str, Any]:
        result = await _exchange_code(self, code, self.redirect_uri, code_verifier)
        return result or {}


@dataclass
class OAuthSession:
    state: str
    provider: str
    redirect_uri: str
    code_verifier: str = ""
    created_at: float = field(default_factory=time.time)
    user_info: dict[str, Any] | None = None


_PROVIDERS: dict[str, OAuthProvider] = {}
_SESSIONS: dict[str, OAuthSession] = {}
_SESSION_TTL = 600  # 10 minutes

# Строгий allowlist разрешённых redirect URI (exact match)
_ALLOWED_REDIRECT_URIS: set[str] | None = None


def _get_allowed_uris() -> set[str]:
    global _ALLOWED_REDIRECT_URIS
    if _ALLOWED_REDIRECT_URIS is None:
        base = settings.oauth_redirect_base.rstrip("/")
        uris = {base}
        # dev-окружение
        uris.add("http://localhost:5173/oauth/callback")
        uris.add("http://localhost:3000/oauth/callback")
        uris.add(base + "/oauth/callback")
        _ALLOWED_REDIRECT_URIS = uris
    return _ALLOWED_REDIRECT_URIS


def generate_state() -> str:
    """Генерирует криптографически стойкий state (128 бит)."""
    return secrets.token_urlsafe(16)


def generate_pkce_pair() -> tuple[str, str]:
    """Генерирует PKCE code_verifier и code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def register_providers() -> None:
    providers = {
        "google": OAuthProvider(
            name="google",
            client_id=settings.oauth_google_client_id.get_secret_value() or "",
            client_secret=settings.oauth_google_client_secret.get_secret_value() or "",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106
            userinfo_url="https://www.googleapis.com/oauth2/v2/userinfo",
            scopes=["openid", "email", "profile"],
            icon="G",
        ),
        "github": OAuthProvider(
            name="github",
            client_id=settings.oauth_github_client_id.get_secret_value() or "",
            client_secret=settings.oauth_github_client_secret.get_secret_value() or "",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",  # noqa: S106
            userinfo_url="https://api.github.com/user",
            scopes=["read:user", "user:email"],
            icon="GH",
        ),
        "microsoft": OAuthProvider(
            name="microsoft",
            client_id=settings.oauth_microsoft_client_id.get_secret_value() or "",
            client_secret=settings.oauth_microsoft_client_secret.get_secret_value() or "",
            authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",  # noqa: S106
            userinfo_url="https://graph.microsoft.com/v1.0/me",
            scopes=["User.Read", "email", "openid"],
            icon="MS",
        ),
    }
    for name, p in providers.items():
        p.enabled = bool(p.client_id and p.client_secret)
        _PROVIDERS[name] = p


def get_enabled_providers() -> list[dict[str, Any]]:
    return [
        {"name": p.name, "icon": p.icon, "enabled": p.enabled}
        for p in _PROVIDERS.values()
    ]


def validate_redirect_uri(uri: str) -> bool:
    from urllib.parse import urlparse as _urlparse

    if not uri:
        return False
    parsed = _urlparse(uri)
    if parsed.scheme not in ("http", "https"):
        return False
    normalized = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    return normalized in _get_allowed_uris()


def get_authorize_url(provider_name: str, redirect_uri: str) -> str | None:
    provider = _PROVIDERS.get(provider_name)
    if not provider or not provider.enabled:
        return None
    if not validate_redirect_uri(redirect_uri):
        return None
    state = generate_state()
    code_verifier, code_challenge = generate_pkce_pair()
    _SESSIONS[state] = OAuthSession(
        state=state,
        provider=provider_name,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    _cleanup_sessions()
    params = {
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(provider.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
    }
    if provider_name == "google":
        params["prompt"] = "consent"
    return f"{provider.authorize_url}?{urlencode(params)}"


async def handle_callback(provider_name: str, code: str, state: str) -> dict[str, Any] | None:
    if not state:
        return None
    session = _SESSIONS.pop(state, None)
    if not session or session.provider != provider_name:
        return None
    if not secrets.compare_digest(state, session.state):
        return None
    provider = _PROVIDERS.get(provider_name)
    if not provider:
        return None

    token_data = await _exchange_code(provider, code, session.redirect_uri, session.code_verifier)
    if not token_data:
        return None

    access_token = token_data.get("access_token")
    if not access_token:
        return None

    user_info = await _fetch_userinfo(provider, access_token)
    if not user_info:
        return None

    email = user_info.get("email", "") or user_info.get("mail", "") or f"{user_info.get('login', 'unknown')}@oauth"
    name = user_info.get("name", "") or user_info.get("displayName", "") or user_info.get("login", email)

    result: dict[str, Any] = {
        "provider": provider_name,
        "email": email,
        "name": name,
        "user_id": f"oauth:{provider_name}:{user_info.get('id', '') or user_info.get('sub', '')}",
        "avatar_url": user_info.get("picture", "") or user_info.get("avatar_url", ""),
    }
    if provider_name == "github":
        result["access_token"] = access_token
        gh_scopes = token_data.get("scope", "")
        result["scope"] = gh_scopes
    return result


async def _exchange_code(provider: OAuthProvider, code: str, redirect_uri: str, code_verifier: str = "") -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Accept": "application/json"}
            if provider.name == "github":
                headers["Accept"] = "application/json"
            data: dict[str, Any] = {
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
            if code_verifier:
                data["code_verifier"] = code_verifier
            resp = await client.post(
                provider.token_url,
                data=data,
                headers=headers,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data
    except httpx.RequestError:
        return None


async def _fetch_userinfo(provider: OAuthProvider, access_token: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            if provider.name == "github":
                headers["Accept"] = "application/json"
                headers["User-Agent"] = "Raven-AI"
            resp = await client.get(provider.userinfo_url, headers=headers)
            if resp.status_code != 200:
                return None
            data: dict[str, Any] = resp.json()
            if provider.name == "github" and not data.get("email"):
                emails_resp = await client.get("https://api.github.com/user/emails", headers=headers)
                if emails_resp.status_code == 200:
                    emails: list[dict[str, Any]] = emails_resp.json()
                    primary: dict[str, Any] = next((e for e in emails if e.get("primary")), {})
                    data["email"] = primary.get("email", "")
            return data
    except httpx.RequestError:
        return None


def _cleanup_sessions() -> None:
    now = time.time()
    for state, session in list(_SESSIONS.items()):
        if now - session.created_at > _SESSION_TTL:
            del _SESSIONS[state]


@dataclass
class OAuthToken:
    access_token: str
    refresh_token: str = ""
    expires_in: int = 0


class OAuthFlow:
    def __init__(self, provider: OAuthProvider):
        self.provider = provider

    async def initiate(self, session: Any) -> dict[str, Any]:
        state = generate_state()
        code_verifier, code_challenge = generate_pkce_pair()

        await session.set("oauth_state", state)
        await session.set("pkce_verifier", code_verifier)

        params = {
            "client_id": self.provider.client_id,
            "response_type": "code",
            "redirect_uri": self.provider.redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{self.provider.authorize_url}?{urlencode(params)}"
        return {"auth_url": auth_url}

    async def handle_callback(
        self,
        code: str,
        state: str,
        session: Any,
    ) -> OAuthToken:
        stored_state = await session.get("oauth_state")
        if not stored_state or not secrets.compare_digest(state, stored_state):
            raise ValueError("Invalid state parameter")

        code_verifier = await session.get("pkce_verifier")
        if not code_verifier:
            raise ValueError("PKCE verifier not found")

        token_data = await self.provider.exchange_code(code=code, code_verifier=code_verifier)

        await session.delete("oauth_state")
        await session.delete("pkce_verifier")

        return OAuthToken(
            access_token=token_data.get("access_token", ""),
            refresh_token=token_data.get("refresh_token", ""),
            expires_in=token_data.get("expires_in", 0),
        )
