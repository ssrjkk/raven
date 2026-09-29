from __future__ import annotations

import hmac

from fastapi import Request

from raven.core.auth.tokens import token_manager
from raven.core.config import get_settings


def authorize_request(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    token = request.headers.get("X-Raven-Key", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        return False
    if token_manager.validate_token(token):
        return True
    key = get_settings().web_secret_key.get_secret_value()
    return bool(key) and hmac.compare_digest(token, key)
