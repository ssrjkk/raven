from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.auth.tokens import token_manager


class AuthHandler:
    async def decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            data = token_manager.validate_token(token)
            if not data:
                return None
            return {
                "sub": data["user_id"],
                "role": data["role"],
                "exp": data["expires_at"],
            }
        except Exception as e:
            logger.debug("Token decode failed: {}", e)
            return None

    def create_token(self, user_id: str, role: str, ttl_seconds: int = 86400) -> str:
        return token_manager.create_token(user_id, role, ttl_seconds)

    def revoke_token(self, token: str) -> None:
        token_manager.revoke_token(token)


auth_handler = AuthHandler()
