from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from raven.core.auth.store import AuthStore


class TokenManager:
    """Bearer sessions.

    With an AuthStore bound, a session is a row in auth_sessions holding a digest of the
    credential: it survives a restart and stops working the moment the user is deactivated.
    Without a store the manager keeps the table in this process, which is all a standalone
    daemon can offer.
    """

    def __init__(self) -> None:
        self._store: AuthStore | None = None
        self._tokens: dict[str, dict[str, Any]] = {}

    def bind(self, store: AuthStore | None) -> None:
        self._store = store

    def unbind(self, store: AuthStore) -> None:
        if self._store is store:
            self._store = None

    async def create_token(self, user_id: str, role: str, ttl_seconds: int = 86400) -> str:
        if self._store is not None:
            return await self._store.create_session(user_id, role, ttl_seconds)
        token = secrets.token_hex(32)
        now = time.time()
        self._tokens[token] = {
            "user_id": user_id,
            "role": role,
            "created_at": now,
            "expires_at": now + ttl_seconds,
        }
        return token

    async def validate_token(self, token: str) -> dict[str, Any] | None:
        if self._store is not None:
            return await self._store.get_session(token)
        data = self._tokens.get(token)
        if not data:
            return None
        if time.time() >= data["expires_at"]:
            self._tokens.pop(token, None)
            return None
        return data

    async def revoke_token(self, token: str) -> None:
        if self._store is not None:
            await self._store.revoke_session(token)
            return
        self._tokens.pop(token, None)

    async def revoke_user_tokens(self, user_id: str) -> None:
        if self._store is not None:
            await self._store.revoke_all_user_sessions(user_id)
            return
        for token in [t for t, d in self._tokens.items() if d["user_id"] == user_id]:
            self._tokens.pop(token, None)


token_manager = TokenManager()
