from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from loguru import logger

from ravencode.integrations.github import GitHubIntegration, parse_github_webhook

app = FastAPI(title="RavenCode GitHub Webhook")
_integration: GitHubIntegration | None = None
_webhook_secret: str = ""


def verify_signature(payload: bytes, signature_header: str | None) -> bool:
    if not _webhook_secret or not signature_header:
        return True
    expected = "sha256=" + hmac.new(_webhook_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.post("/webhook")
async def webhook_handler(request: Request) -> dict[str, Any]:
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(body, sig):
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_name = request.headers.get("X-GitHub-Event", "")
    if not event_name:
        raise HTTPException(status_code=400, detail="Missing X-GitHub-Event header")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    ctx = parse_github_webhook(event_name, payload)
    if ctx is None:
        return {"status": "ignored", "reason": f"Unhandled event type: {event_name}"}

    if ctx.event_type.value in ("issue_comment.created", "pull_request_review_comment.created") and ctx.comment_body:
            stripped = ctx.comment_body.strip().lower()
            if not any(stripped.startswith(p) for p in ("/ravencode", "/rc", "@ravencode")):
                return {"status": "ignored", "reason": "Not a ravencode command"}

    if _integration is None:
        raise HTTPException(status_code=500, detail="Integration not initialized")

    result = await _integration.handle_event(ctx)
    return {
        "status": "processed",
        "event": event_name,
        "result": result.summary if result else "No action",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def run_webhook_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    token: str | None = None,
    secret: str | None = None,
) -> None:
    global _integration, _webhook_secret
    _integration = GitHubIntegration(token=token)
    _webhook_secret = secret if secret is not None else os.getenv("GITHUB_WEBHOOK_SECRET", "")
    logger.info("Starting GitHub webhook server on {}:{}", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
