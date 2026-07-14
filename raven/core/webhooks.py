from __future__ import annotations

import hashlib
import hmac as hmac_mod
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from raven.core.config import settings
from raven.core.db import Database
from raven.core.models import IncomingMessage


def _verify_hmac_sha256(body_bytes: bytes, signature: str, secret: str) -> bool:
    expected = hmac_mod.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return hmac_mod.compare_digest(f"sha256={expected}", signature)


async def _verify_webhook_signature(request: Request) -> None:
    if settings.web_secret_key:
        body_bytes = await request.body()
        sig = request.headers.get("X-Webhook-Signature", "")
        if sig and not _verify_hmac_sha256(body_bytes, sig, settings.web_secret_key):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")


def create_webhook_router(db: Database, handle_incoming: Any) -> APIRouter:
    router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

    @router.post("/generic")
    async def generic_webhook(body: dict[str, Any], request: Request):
        body_bytes = await request.body()
        signature = request.headers.get("X-Webhook-Signature", "")
        if settings.web_secret_key:
            if not signature or not _verify_hmac_sha256(body_bytes, signature, settings.web_secret_key):
                raise HTTPException(status_code=403, detail="Invalid or missing webhook signature")
        elif signature:
            raise HTTPException(status_code=403, detail="Webhook signature not supported — WEB_SECRET_KEY not configured")
        source = request.headers.get("X-Webhook-Source", "unknown")
        text = body.get("text", "") or body.get("message", "") or body.get("content", "")
        user_id = body.get("user_id", "") or body.get("user", "") or f"webhook:{source}"
        if not text:
            raise HTTPException(status_code=400, detail="No text content")
        from raven.core.security.context_filter import sanitize_external_content

        text = sanitize_external_content(text, source=source, channel="webhook", sender=user_id)
        safe_keys = {"source", "channel", "user_id", "text", "message", "content", "type", "event", "timestamp"}
        safe_body = {k: v for k, v in body.items() if k in safe_keys} if isinstance(body, dict) else {}
        event = IncomingMessage(
            channel="webhook",
            user_id=user_id,
            session_id=f"webhook:{source}:{user_id}",
            text=text,
            metadata={"source": source, "body": safe_body},
        )
        await handle_incoming(event)
        return {"ok": True, "source": source}

    @router.post("/slack/events")
    async def slack_events(body: dict[str, Any], request: Request):
        body_bytes = await request.body()
        slack_sig = request.headers.get("X-Slack-Signature", "")
        slack_ts = request.headers.get("X-Slack-Request-Timestamp", "")
        if settings.web_secret_key and slack_sig:
            try:
                ts = int(slack_ts)
                if abs(time.time() - ts) > 300:
                    raise HTTPException(status_code=403, detail="Slack request timestamp too old")
            except (ValueError, TypeError) as err:
                raise HTTPException(status_code=403, detail="Invalid Slack timestamp") from err
            sig_basestring = f"v0:{slack_ts}:{body_bytes.decode()}"
            expected = "v0=" + hmac_mod.new(
                settings.web_secret_key.encode(), sig_basestring.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac_mod.compare_digest(expected, slack_sig):
                raise HTTPException(status_code=403, detail="Invalid Slack signature")
        logger.debug("Slack webhook event: {}", body.get("type", ""))
        if body.get("type") == "url_verification":
            return {"challenge": body.get("challenge", "")}
        event = body.get("event", {})
        slack_ch = request.app.state.slack_channel if hasattr(request.app.state, "slack_channel") else None
        if slack_ch:
            await slack_ch.handle_event(event, body.get("team_id"))
        return {"ok": True}

    @router.post("/whatsapp")
    async def whatsapp_webhook(body: dict[str, Any], request: Request):
        body_bytes = await request.body()
        wa_sig = request.headers.get("X-Hub-Signature-256", "")
        if settings.web_secret_key and wa_sig and not _verify_hmac_sha256(body_bytes, wa_sig, settings.web_secret_key):
            raise HTTPException(status_code=403, detail="Invalid WhatsApp signature")
        wa_ch = request.app.state.whatsapp_channel if hasattr(request.app.state, "whatsapp_channel") else None
        if wa_ch:
            await wa_ch.handle_webhook(body)
        return {"ok": True}

    @router.get("/whatsapp")
    async def whatsapp_verify(request: Request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and settings.web_secret_key and hmac_mod.compare_digest(token or "", settings.web_secret_key):
            return int(challenge)  # type: ignore[arg-type]
        raise HTTPException(status_code=403, detail="Verify token failed")

    @router.post("/googlechat")
    async def googlechat_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.googlechat_channel if hasattr(request.app.state, "googlechat_channel") else None
        if not ch:
            logger.warning("googlechat channel not configured, webhook ignored")
            return {"ok": False, "error": "googlechat channel not configured"}
        await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/signal")
    async def signal_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.signal_channel if hasattr(request.app.state, "signal_channel") else None
        if not ch:
            logger.warning("signal channel not configured, webhook ignored")
            return {"ok": False, "error": "signal channel not configured"}
        await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/teams")
    async def teams_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.teams_channel if hasattr(request.app.state, "teams_channel") else None
        if not ch:
            logger.warning("teams channel not configured, webhook ignored")
            return {"ok": False, "error": "teams channel not configured"}
        await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/feishu")
    async def feishu_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.feishu_channel if hasattr(request.app.state, "feishu_channel") else None
        if not ch:
            logger.warning("feishu channel not configured, webhook ignored")
            return {"ok": False, "error": "feishu channel not configured"}
        await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/line")
    async def line_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.line_channel if hasattr(request.app.state, "line_channel") else None
        if not ch:
            logger.warning("line channel not configured, webhook ignored")
            return {"ok": False, "error": "line channel not configured"}
        await ch.handle_webhook(body)
        return {"ok": True}

    @router.post("/github")
    async def github_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.github_channel if hasattr(request.app.state, "github_channel") else None
        if not ch:
            logger.warning("github channel not configured, webhook ignored")
            return {"ok": False, "error": "github channel not configured"}
        headers = dict(request.headers)
        await ch.handle_webhook(body, headers)
        return {"ok": True}

    @router.post("/gitlab")
    async def gitlab_webhook(body: dict[str, Any], request: Request):
        await _verify_webhook_signature(request)
        ch = request.app.state.gitlab_channel if hasattr(request.app.state, "gitlab_channel") else None
        if not ch:
            logger.warning("gitlab channel not configured, webhook ignored")
            return {"ok": False, "error": "gitlab channel not configured"}
        headers = dict(request.headers)
        await ch.handle_webhook(body, headers)
        return {"ok": True}

    @router.post("/github-actions")
    async def github_actions_webhook(body: dict[str, Any], request: Request):
        workflow_run = body.get("workflow_run", {}) or {}
        action = body.get("action", "")
        conclusion = workflow_run.get("conclusion", "")
        if action != "completed" or conclusion != "failure":
            return {"ok": True, "skipped": True}
        repo_info = body.get("repository", {}) or {}
        repo_full = repo_info.get("full_name", "")
        repo_path = repo_info.get("name", "")
        owner = repo_full.split("/")[0] if "/" in repo_full else ""
        head_branch = workflow_run.get("head_branch", "")
        head_sha = workflow_run.get("head_commit", {}).get("id", "") if workflow_run.get("head_commit") else ""
        logger.info("GitHub Actions failure: {}/{} branch={}", owner, repo_path, head_branch)
        try:
            from raven.qa_healer.analyzer import FailureReport, TestFailure
            from raven.qa_healer.healer import heal_test_failure

            report = FailureReport()
            report.failed = 1
            report.suite_name = workflow_run.get("name", "CI Pipeline")
            report.failures.append(
                TestFailure(
                    test_name=f"workflow:{workflow_run.get('name', 'unknown')}",
                    test_file="",
                    error_message=f"Workflow '{workflow_run.get('name', '')}' failed on branch '{head_branch}' (commit {head_sha[:8]})",
                )
            )
            result = await heal_test_failure(report.failures[0], ".")
            if result.get("fix_applied"):
                return {"ok": True, "healed": True, "branch": result.get("branch")}
            return {"ok": True, "healed": False, "error": result.get("error")}
        except ImportError:
            logger.warning("qa_healer module not available, skipping auto-heal")
            return {"ok": True}
        except Exception as exc:
            logger.error("Auto-heal failed: {}", exc)
            return {"ok": True, "healed": False, "error": "Auto-heal failed"}

    @router.post("/allure")
    async def allure_webhook(body: dict[str, Any], request: Request):
        results_url = body.get("results_url", "") or body.get("results_path", "")
        if not results_url:
            raise HTTPException(status_code=400, detail="No results_url or results_path provided")
        auto_pr = body.get("auto_pr", False)
        repo_path = body.get("repo_path", ".")
        logger.info("Allure webhook: results={}, auto_pr={}", results_url, auto_pr)
        try:
            from raven.qa_healer.healer import qa_heal_all

            report = await qa_heal_all(results_url, repo_path, auto_pr=auto_pr)
            return {"ok": True, "report": report}
        except ImportError:
            logger.warning("qa_healer module not available")
            return {"ok": True, "message": "qa_healer not installed"}
        except Exception as exc:
            logger.error("Allure auto-heal failed: {}", exc)
            return {"ok": True, "error": "Allure auto-heal failed"}

    return router
