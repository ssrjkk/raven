from __future__ import annotations

import hmac
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from raven.core.auth.tokens import token_manager
from raven.core.config import settings
from raven.core.sse import sse_stream


def create_sse_router() -> APIRouter:
    router = APIRouter()

    @router.get("/events/sessions")
    async def events_sessions(request: Request):
        token = request.query_params.get("token", "")
        user: str | None = None
        if token:
            session = token_manager.validate_token(token)
            if session:
                user = str(session.get("user_id", "")) or None
            elif settings.web_secret_key.get_secret_value() and hmac.compare_digest(
                token, settings.web_secret_key.get_secret_value()
            ):
                user = "admin"
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required or invalid token")

        async def event_generator() -> Any:
            key = f"sse-sessions:{user}:{uuid.uuid4().hex[:8]}"
            async for chunk in sse_stream.stream(key):
                yield chunk

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
