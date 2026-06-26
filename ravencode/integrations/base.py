from __future__ import annotations

from abc import ABC, abstractmethod

from ravencode.integrations.models import EventContext as EventContext
from ravencode.integrations.models import EventType as EventType
from ravencode.integrations.models import WorkflowResult as WorkflowResult


class CIProvider(ABC):
    """Base class for CI/CD provider integrations (GitHub, GitLab, etc.)."""

    def __init__(self, token: str | None = None, api_url: str | None = None):
        self._token = token
        self._api_url = api_url

    @abstractmethod
    async def post_comment(self, ctx: EventContext, body: str) -> bool:
        ...

    @abstractmethod
    async def get_file_content(self, ctx: EventContext, path: str, ref: str | None = None) -> str | None:
        ...

    @abstractmethod
    async def create_branch(self, ctx: EventContext, base: str, head: str) -> bool:
        ...

    @abstractmethod
    async def create_pr(self, ctx: EventContext, title: str, body: str, head: str, base: str) -> int | None:
        ...

    @abstractmethod
    async def get_pr_diff(self, ctx: EventContext, pr_number: int) -> str | None:
        ...

    @abstractmethod
    async def set_commit_status(self, ctx: EventContext, sha: str, state: str, description: str) -> bool:
        ...

    async def handle_event(self, ctx: EventContext) -> WorkflowResult | None:
        """Route event to appropriate handler. Override in subclass."""
        if ctx.event_type == EventType.ISSUE_COMMENT and ctx.comment_body:
            return await self._handle_issue_comment(ctx)
        if ctx.event_type == EventType.PR_OPENED:
            return await self._handle_pr_opened(ctx)
        if ctx.event_type == EventType.ISSUE_OPENED:
            return await self._handle_issue_opened(ctx)
        if ctx.event_type == EventType.PR_REVIEW_REQUESTED:
            return await self._handle_pr_review(ctx)
        return None

    async def _handle_issue_comment(self, ctx: EventContext) -> WorkflowResult | None:
        return None

    async def _handle_pr_opened(self, ctx: EventContext) -> WorkflowResult | None:
        return None

    async def _handle_issue_opened(self, ctx: EventContext) -> WorkflowResult | None:
        return None

    async def _handle_pr_review(self, ctx: EventContext) -> WorkflowResult | None:
        return None
