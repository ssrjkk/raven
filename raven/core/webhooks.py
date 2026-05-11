from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Request, HTTPException
from loguru import logger
from raven.core.models import Message, IncomingMessage
from raven.core.db import Database
from raven.core.logging import audit
from raven.core.config import settings


def create_webhook_router(db: Database, handle_incoming: Any) -> APIRouter:
    router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

    @router.post("/generic")
    async def generic_webhook(body: dict, request: Request):
        source = request.headers.get("X-Webhook-Source", "unknown")
        text = body.get("text", "") or body.get("message", "") or body.get("content", "")
        user_id = body.get("user_id", "") or body.get("user", "") or f"webhook:{source}"
        if not text:
            raise HTTPException(status_code=400, detail="No text content")
        event = IncomingMessage(
            channel="webhook",
            user_id=user_id,
            session_id=f"webhook:{source}:{user_id}",
            text=text,
            metadata={"source": source, "body": body},
        )
        await handle_incoming(event)
        return {"ok": True, "source": source}

    @router.post("/slack/events")
    async def slack_events(body: dict, request: Request):
        logger.debug("Slack webhook event: {}", body.get("type", ""))
        if body.get("type") == "url_verification":
            return {"challenge": body.get("challenge", "")}
        event = body.get("event", {})
        slack_ch = request.app.state.slack_channel if hasattr(request.app.state, "slack_channel") else None
        if slack_ch:
            await slack_ch.handle_event(event, body.get("team_id"))
        return {"ok": True}

    @router.post("/whatsapp")
    async def whatsapp_webhook(body: dict, request: Request):
        wa_ch = request.app.state.whatsapp_channel if hasattr(request.app.state, "whatsapp_channel") else None
        if wa_ch:
            await wa_ch.handle_webhook(body)
        return {"ok": True}

    @router.get("/whatsapp")
    async def whatsapp_verify(request: Request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and token == settings.web_secret_key:
            return int(challenge)
        raise HTTPException(status_code=403, detail="Verify token failed")

    @router.post("/googlechat")
    async def googlechat_webhook(body: dict, request: Request):
        ch = request.app.state.googlechat_channel if hasattr(request.app.state, "googlechat_channel") else None
        if ch:
            await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/signal")
    async def signal_webhook(body: dict, request: Request):
        ch = request.app.state.signal_channel if hasattr(request.app.state, "signal_channel") else None
        if ch:
            await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/teams")
    async def teams_webhook(body: dict, request: Request):
        ch = request.app.state.teams_channel if hasattr(request.app.state, "teams_channel") else None
        if ch:
            await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/feishu")
    async def feishu_webhook(body: dict, request: Request):
        ch = request.app.state.feishu_channel if hasattr(request.app.state, "feishu_channel") else None
        if ch:
            await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/line")
    async def line_webhook(body: dict, request: Request):
        ch = request.app.state.line_channel if hasattr(request.app.state, "line_channel") else None
        if ch:
            await ch.handle_webhook(body)
        return {"ok": True}

    return router
