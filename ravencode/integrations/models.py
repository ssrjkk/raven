from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    ISSUE_OPENED = "issues.opened"
    ISSUE_COMMENT = "issue_comment.created"
    PR_OPENED = "pull_request.opened"
    PR_COMMENT = "pull_request_review_comment.created"
    PR_REVIEW_REQUESTED = "pull_request.review_requested"
    PUSH = "push"
    SCHEDULE = "schedule"
    WORKFLOW_DISPATCH = "workflow_dispatch"
    MERGE_REQUEST_OPENED = "merge_request.opened"
    MERGE_REQUEST_COMMENT = "merge_request_comment"


@dataclass
class EventContext:
    event_type: EventType
    platform: str
    repo: str
    owner: str
    ref: str | None = None
    sha: str | None = None
    issue_number: int | None = None
    pr_number: int | None = None
    comment_id: int | None = None
    comment_body: str | None = None
    title: str | None = None
    body: str | None = None
    sender: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass
class WorkflowResult:
    success: bool
    summary: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
