from __future__ import annotations

import secrets
import time
from typing import Any

from loguru import logger


class TokenManager:
    def __init__(self):
        self._tokens: dict[str, dict[str, Any]] = {}

    def create_token(self, user_id: str, role: str, ttl_seconds: int = 86400) -> str:
        token = secrets.token_hex(32)
        self._tokens[token] = {
            "user_id": user_id,
            "role": role,
            "created_at": time.time(),
            "expires_at": time.time() + ttl_seconds,
        }
        return token

    def validate_token(self, token: str) -> dict[str, Any] | None:
        data = self._tokens.get(token)
        if not data:
            return None
        if time.time() > data["expires_at"]:
            self.revoke_token(token)
            return None
        return data

    def revoke_token(self, token: str):
        self._tokens.pop(token, None)

    def revoke_user_tokens(self, user_id: str):
        to_revoke = [t for t, d in self._tokens.items() if d["user_id"] == user_id]
        for t in to_revoke:
            self.revoke_token(t)

    def clean_expired(self):
        now = time.time()
        to_remove = [t for t, d in self._tokens.items() if now > d["expires_at"]]
        for t in to_remove:
            self._tokens.pop(t, None)
        if to_remove:
            logger.debug("Cleaned {} expired tokens", len(to_remove))

    def count(self) -> int:
        return len(self._tokens)


token_manager = TokenManager()
