from __future__ import annotations

import hmac
from typing import Any

from ravencode.integrations.models import EventType
from ravencode.integrations.vcs.webhook import (
    WebhookEvent,
    WebhookEventType,
)


class GitLabWebhookNormalizer:
    def validate_signature(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
        token = headers.get("X-Gitlab-Token", "")
        if not secret:
            return False
        return hmac.compare_digest(token, secret)

    def normalize(self, raw_payload: dict[str, Any]) -> WebhookEvent:
        object_kind = raw_payload.get("object_kind")

        if object_kind == "push":
            return WebhookEvent(
                event_type=WebhookEventType.PUSH,
                repository=raw_payload["project"]["path_with_namespace"],
                actor=raw_payload["user_username"],
                payload=raw_payload,
                ref=raw_payload["ref"],
            )

        if object_kind == "merge_request":
            attrs = raw_payload["object_attributes"]
            et = (
                WebhookEventType.PULL_REQUEST_OPENED
                if attrs.get("action") in ("open", "opened")
                else WebhookEventType.PULL_REQUEST_CLOSED
            )
            return WebhookEvent(
                event_type=et,
                repository=raw_payload["project"]["path_with_namespace"],
                actor=str(attrs.get("author_id", "")),
                payload=raw_payload,
                ref=attrs.get("source_branch"),
            )

        if object_kind == "issue":
            attrs = raw_payload["object_attributes"]
            et = (
                WebhookEventType.ISSUE_OPENED
                if attrs.get("action") in ("open", "opened")
                else WebhookEventType.ISSUE_CLOSED
            )
            return WebhookEvent(
                event_type=et,
                repository=raw_payload["project"]["path_with_namespace"],
                actor=str(attrs.get("author_id", "")),
                payload=raw_payload,
            )

        msg = f"Unsupported GitLab event: {object_kind}"
        raise ValueError(msg)


class GitLabLegacyNormalizer:
    def detect_event_type(self, raw_event: str, payload: dict[str, Any]) -> EventType | None:
        mapping: dict[str, EventType] = {
            "Issue Hook": EventType.ISSUE_OPENED,
            "Note Hook": EventType.ISSUE_COMMENT,
            "Merge Request Hook": EventType.MERGE_REQUEST_OPENED,
        }
        base = mapping.get(raw_event)
        if base is None:
            return None
        if raw_event == "Note Hook":
            noteable = (payload.get("object_attributes") or {}).get("noteable_type") or ""
            if noteable == "MergeRequest":
                return EventType.MERGE_REQUEST_COMMENT
            return EventType.ISSUE_COMMENT
        return base

    def get_owner(self, payload: dict[str, Any]) -> str:
        path = (payload.get("project") or {}).get("path_with_namespace", "")
        parts = path.split("/", 1)
        return parts[0] if len(parts) == 2 else ""

    def get_repo(self, payload: dict[str, Any]) -> str:
        path = (payload.get("project") or {}).get("path_with_namespace", "")
        parts = path.split("/", 1)
        return parts[1] if len(parts) == 2 else ""

    def get_sender(self, payload: dict[str, Any]) -> str | None:
        return (payload.get("user") or {}).get("username")

    def get_sha(self, payload: dict[str, Any]) -> str | None:
        attrs = payload.get("object_attributes") or {}
        last_commit = attrs.get("last_commit")
        if isinstance(last_commit, dict):
            return last_commit.get("id")
        return None

    def get_ref(self, payload: dict[str, Any]) -> str | None:
        return payload.get("ref")

    def extract_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        attrs = payload.get("object_attributes") or {}
        return {
            "iid": attrs.get("iid"),
            "title": attrs.get("title"),
            "description": attrs.get("description"),
        }

    def extract_comment(self, payload: dict[str, Any]) -> dict[str, Any]:
        attrs = payload.get("object_attributes") or {}
        return {
            "id": attrs.get("id"),
            "note": attrs.get("note"),
        }

    def extract_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        mr = payload.get("merge_request") or {}
        attrs = payload.get("object_attributes") or {}
        return {
            "iid": mr.get("iid") or attrs.get("iid"),
            "title": mr.get("title") or attrs.get("title"),
            "description": mr.get("description") or attrs.get("description"),
        }
