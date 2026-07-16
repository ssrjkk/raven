from __future__ import annotations

import hashlib
import hmac
from typing import Any

from ravencode.integrations.models import EventType
from ravencode.integrations.vcs.webhook import (
    WebhookEvent,
    WebhookEventType,
)


class GitHubWebhookNormalizer:
    def validate_signature(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        signature = headers.get("X-Hub-Signature-256", "")
        if not signature.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    def normalize(self, raw_payload: dict[str, Any]) -> WebhookEvent:
        action = raw_payload.get("action")

        if "ref" in raw_payload and "pusher" in raw_payload:
            return WebhookEvent(
                event_type=WebhookEventType.PUSH,
                repository=raw_payload["repository"]["full_name"],
                actor=raw_payload["pusher"]["name"],
                payload=raw_payload,
                ref=raw_payload["ref"],
            )

        if "pull_request" in raw_payload:
            pr = raw_payload["pull_request"]
            et = (
                WebhookEventType.PULL_REQUEST_OPENED
                if action == "opened"
                else WebhookEventType.PULL_REQUEST_CLOSED
            )
            return WebhookEvent(
                event_type=et,
                repository=raw_payload["repository"]["full_name"],
                actor=pr["user"]["login"],
                payload=raw_payload,
                ref=pr["head"]["ref"],
            )

        if "issue" in raw_payload:
            issue = raw_payload["issue"]
            et = (
                WebhookEventType.ISSUE_OPENED
                if action == "opened"
                else WebhookEventType.ISSUE_CLOSED
            )
            return WebhookEvent(
                event_type=et,
                repository=raw_payload["repository"]["full_name"],
                actor=issue["user"]["login"],
                payload=raw_payload,
            )

        raise ValueError("Unsupported GitHub event payload")


class GitHubLegacyNormalizer:
    EVENT_MAP: dict[str, EventType] = {
        "issues": EventType.ISSUE_OPENED,
        "issue_comment": EventType.ISSUE_COMMENT,
        "pull_request": EventType.PR_OPENED,
        "pull_request_review_comment": EventType.PR_COMMENT,
        "pull_request_review": EventType.PR_REVIEW_REQUESTED,
        "push": EventType.PUSH,
    }

    def detect_event_type(self, raw_event: str, payload: dict[str, Any]) -> EventType | None:
        return self.EVENT_MAP.get(raw_event)

    def get_owner(self, payload: dict[str, Any]) -> str:
        repo_full = (payload.get("repository") or {}).get("full_name", "")
        parts = repo_full.split("/", 1)
        return parts[0] if len(parts) == 2 else ""

    def get_repo(self, payload: dict[str, Any]) -> str:
        repo_full = (payload.get("repository") or {}).get("full_name", "")
        parts = repo_full.split("/", 1)
        return parts[1] if len(parts) == 2 else ""

    def get_sender(self, payload: dict[str, Any]) -> str | None:
        return (payload.get("sender") or {}).get("login")

    def get_sha(self, payload: dict[str, Any]) -> str | None:
        return payload.get("after")

    def get_ref(self, payload: dict[str, Any]) -> str | None:
        return payload.get("ref")

    def extract_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        issue = payload.get("issue") or {}
        return {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "body": issue.get("body"),
        }

    def extract_comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        comment = payload.get("comment") or {}
        return {
            "id": comment.get("id"),
            "body": comment.get("body"),
            "note": comment.get("body"),
        }

    def extract_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        pr = payload.get("pull_request") or {}
        return {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "body": pr.get("body"),
        }
