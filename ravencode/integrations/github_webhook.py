from __future__ import annotations

import os
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from loguru import logger

from raven.core.security.ssrf import binds_every_interface
from ravencode.integrations.github import GitHubIntegration, parse_github_webhook_request
from ravencode.integrations.vcs.webhook import WebhookEventType, webhook_event_to_context

app = FastAPI(title="RavenCode GitHub Webhook")
_integration: GitHubIntegration | None = None
_webhook_secret: str = ""


@app.post("/webhook")
async def webhook_handler(request: Request) -> dict[str, Any]:
    try:
        event = await parse_github_webhook_request(request, _webhook_secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if _integration is None:
        raise HTTPException(status_code=500, detail="Integration not initialized")

    if event.event_type in (
        WebhookEventType.PULL_REQUEST_COMMENT,
        WebhookEventType.ISSUE_COMMENT,
    ):
        stripped = event.payload.get("comment", {}).get("body", "").strip().lower()
        if not any(stripped.startswith(p) for p in ("/ravencode", "/rc", "@ravencode")):
            return {"status": "ignored", "reason": "Not a ravencode command"}

    ctx = webhook_event_to_context(event)
    ctx.platform = "github"
    result = await _integration.handle_event(ctx)
    return {
        "status": "processed",
        "event": event.event_type.value,
        "result": result.summary if result else "No action",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def run_webhook_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    token: str | None = None,
    secret: str | None = None,
) -> None:
    global _integration, _webhook_secret
    _integration = GitHubIntegration(token=token)
    _webhook_secret = secret if secret is not None else os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if binds_every_interface(host):
        logger.warning("Binding to {}:{}. Ensure firewall/reverse proxy is configured.", host, port)
    logger.info("Starting GitHub webhook server on {}:{}", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
