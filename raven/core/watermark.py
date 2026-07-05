"""Watermarking utilities for tracing the origin of leaked builds.

Each deploy gets a unique DEPLOY_ID baked into the binary.
Injected into:
- User-Agent headers (outbound HTTP)
- Canary HTML comments (web UI responses)
- Honeytoken keys (fake credentials that trigger alerts if used)
"""
from __future__ import annotations

from raven.core._deploy import DEPLOY_ID, DEPLOY_ORIGIN, DEPLOY_TIMESTAMP

CANARY_PREFIX = "raven-deploy"
HONEYTOKEN_SUFFIXES = ["_h7k", "_h0ney", "_canary", "honeytoken"]

HONEYTOKEN_API_KEYS: dict[str, str] = {
    "OPENROUTER_API_KEY": f"sk-or-v1-honeytoken-{DEPLOY_ID}",
    "ANTHROPIC_API_KEY": f"sk-ant-honeytoken-{DEPLOY_ID}",
    "OPENAI_API_KEY": f"sk-honeytoken-{DEPLOY_ID}",
    "GITHUB_TOKEN": f"ghp_honeytoken_{DEPLOY_ID}",
    "TELEGRAM_BOT_TOKEN": f"{DEPLOY_ID}:honeytoken-telegram-bot",
    "SLACK_BOT_TOKEN": f"xoxb-honeytoken-{DEPLOY_ID}",
}


def user_agent() -> str:
    """User-Agent string identifying this specific deploy."""
    return f"RavenAI/{DEPLOY_ID}"


def canary_html_comment() -> str:
    """Hidden HTML comment for web responses."""
    return f"<!-- {CANARY_PREFIX}-{DEPLOY_ID} -->"


def canary_header() -> dict[str, str]:
    """HTTP response header carrying deploy origin."""
    return {"X-Raven-Deploy": DEPLOY_ID, "X-Raven-Origin": DEPLOY_ORIGIN}


def is_honeytoken(key: str, value: str) -> bool:
    """Check if a credential value matches a known honeytoken pattern."""
    for suffix in HONEYTOKEN_SUFFIXES:
        if suffix in value.lower():
            return True
    return any(key == env_key and value == token for env_key, token in HONEYTOKEN_API_KEYS.items())


def honeytoken_warning(key: str) -> str:
    return (
        f"[watermark] HONEYTOKEN DETECTED: {key} matches a known watermark token "
        f"(deploy={DEPLOY_ID}, origin={DEPLOY_ORIGIN}, ts={DEPLOY_TIMESTAMP})"
    )


def install_fastapi_watermark(app):
    """Add canary response headers to a FastAPI application."""
    from starlette.types import ASGIApp, Receive, Scope, Send

    class WatermarkMiddleware:
        def __init__(self, inner: ASGIApp):
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] != "http":
                await self.inner(scope, receive, send)
                return

            async def send_with_headers(message):
                if message["type"] == "http.response.start":
                    headers = message.get("headers", [])
                    headers.append((b"X-Raven-Deploy", DEPLOY_ID.encode()))
                    headers.append((b"X-Raven-Origin", DEPLOY_ORIGIN.encode()))
                    message["headers"] = headers
                await send(message)

            await self.inner(scope, receive, send_with_headers)

    app.add_middleware(WatermarkMiddleware)

