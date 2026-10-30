from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.auth.tokens import token_manager


class AuthHandler:
    async def decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            data = await token_manager.validate_token(token)
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

    async def create_token(self, user_id: str, role: str, ttl_seconds: int = 86400) -> str:
        return await token_manager.create_token(user_id, role, ttl_seconds)

    async def revoke_token(self, token: str) -> None:
        await token_manager.revoke_token(token)


auth_handler = AuthHandler()
