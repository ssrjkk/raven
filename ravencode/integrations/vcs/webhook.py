from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from fastapi import Request

from ravencode.integrations.models import EventContext, EventType


def webhook_event_to_context(event: WebhookEvent) -> EventContext:
    """Convert a provider-independent WebhookEvent to the legacy EventContext."""
    if event.event_type == WebhookEventType.PUSH:
        ev_type = EventType.PUSH
    elif event.event_type in (WebhookEventType.PULL_REQUEST_OPENED, WebhookEventType.PULL_REQUEST_CLOSED):
        ev_type = EventType.PR_OPENED
    elif event.event_type == WebhookEventType.PULL_REQUEST_COMMENT:
        ev_type = EventType.PR_COMMENT
    elif event.event_type in (WebhookEventType.ISSUE_OPENED, WebhookEventType.ISSUE_CLOSED):
        ev_type = EventType.ISSUE_OPENED
    elif event.event_type == WebhookEventType.ISSUE_COMMENT:
        ev_type = EventType.ISSUE_COMMENT
    else:
        ev_type = EventType.ISSUE_OPENED

    parts = event.repository.split("/", 1)
    owner = parts[0] if len(parts) == 2 else ""
    repo = parts[1] if len(parts) == 2 else ""

    return EventContext(
        event_type=ev_type,
        platform="",
        repo=repo,
        owner=owner,
        raw=event.payload,
        sender=event.actor,
        ref=event.ref,
        sha=None,
    )


class WebhookEventType(Enum):
    PUSH = "push"
    PULL_REQUEST_OPENED = "pr_opened"
    PULL_REQUEST_CLOSED = "pr_closed"
    PULL_REQUEST_COMMENT = "pr_comment"
    ISSUE_OPENED = "issue_opened"
    ISSUE_CLOSED = "issue_closed"
    ISSUE_COMMENT = "issue_comment"


@dataclass(frozen=True)
class WebhookEvent:
    event_type: WebhookEventType
    repository: str
    actor: str
    payload: dict[str, Any]
    ref: str | None = None


class WebhookNormalizer(Protocol):
    def validate_signature(self, headers: dict[str, str], body: bytes, secret: str) -> bool: ...

    def normalize(self, raw_payload: dict[str, Any]) -> WebhookEvent: ...


async def parse_webhook(
    normalizer: WebhookNormalizer,
    request: Request,
    secret: str,
) -> WebhookEvent:
    body = await request.body()
    headers = dict(request.headers)

    if not normalizer.validate_signature(headers, body, secret):
        raise ValueError("Invalid webhook signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON payload: {e}") from e

    return normalizer.normalize(payload)


EVENT_BRANCHES: dict[EventType, str] = {
    EventType.ISSUE_OPENED: "issue",
    EventType.ISSUE_COMMENT: "issue_comment",
    EventType.PR_OPENED: "pr",
    EventType.PR_COMMENT: "pr_comment",
    EventType.PR_REVIEW_REQUESTED: "pr",
    EventType.MERGE_REQUEST_OPENED: "pr",
    EventType.MERGE_REQUEST_COMMENT: "pr_comment",
    EventType.PUSH: "push",
}


class LegacyNormalizer(Protocol):
    def detect_event_type(self, raw_event: str, payload: dict[str, Any]) -> EventType | None: ...
    def get_owner(self, payload: dict[str, Any]) -> str: ...
    def get_repo(self, payload: dict[str, Any]) -> str: ...
    def get_sender(self, payload: dict[str, Any]) -> str | None: ...
    def get_sha(self, payload: dict[str, Any]) -> str | None: ...
    def get_ref(self, payload: dict[str, Any]) -> str | None: ...
    def extract_issue(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def extract_comment(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def extract_pr(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def parse_legacy_webhook(
    normalizer: LegacyNormalizer,
    raw_event: str,
    payload: dict[str, Any],
) -> EventContext | None:
    event_type = normalizer.detect_event_type(raw_event, payload)
    if event_type is None:
        return None

    ctx = EventContext(
        event_type=event_type,
        platform="",
        repo=normalizer.get_repo(payload),
        owner=normalizer.get_owner(payload),
        raw=payload,
        sender=normalizer.get_sender(payload),
        ref=normalizer.get_ref(payload),
        sha=normalizer.get_sha(payload),
    )

    branch = EVENT_BRANCHES.get(event_type)
    if branch == "issue":
        issue = normalizer.extract_issue(payload)
        ctx.issue_number = issue.get("number") or issue.get("iid")
        ctx.title = issue.get("title")
        ctx.body = issue.get("body") or issue.get("description")

    elif branch == "issue_comment":
        issue = normalizer.extract_issue(payload)
        comment = normalizer.extract_comment(payload)
        ctx.issue_number = issue.get("number") or issue.get("iid")
        ctx.title = issue.get("title")
        ctx.body = issue.get("body") or issue.get("description")
        ctx.comment_id = comment.get("id")
        ctx.comment_body = comment.get("body") or comment.get("note")

    elif branch == "pr":
        pr = normalizer.extract_pr(payload)
        ctx.pr_number = pr.get("number") or pr.get("iid")
        ctx.title = pr.get("title")
        ctx.body = pr.get("body") or pr.get("description")

    elif branch == "pr_comment":
        pr = normalizer.extract_pr(payload)
        comment = normalizer.extract_comment(payload)
        ctx.pr_number = pr.get("number") or pr.get("iid")
        ctx.title = pr.get("title")
        ctx.body = pr.get("body") or pr.get("description")
        ctx.comment_id = comment.get("id")
        ctx.comment_body = comment.get("body") or comment.get("note")

    return ctx
