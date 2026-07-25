from __future__ import annotations

from typing import Any

from fastapi import Request

from ravencode.integrations.base import CIProvider, EventContext
from ravencode.integrations.vcs.gitlab_provider import GitLabProvider
from ravencode.integrations.vcs.gitlab_webhook import GitLabLegacyNormalizer, GitLabWebhookNormalizer
from ravencode.integrations.vcs.webhook import WebhookEvent, parse_legacy_webhook, parse_webhook


class GitLabIntegration(CIProvider):
    def __init__(self, token: str | None = None, api_url: str | None = None) -> None:
        super().__init__(token=token, api_url=api_url)
        self._provider = GitLabProvider(token=token, api_url=api_url or "") if token else None

    async def post_comment(self, ctx: EventContext, body: str) -> bool:
        if self._provider is None:
            return False
        identifier = f"{ctx.owner}/{ctx.repo}" if ctx.owner else ctx.repo
        rid = ctx.issue_number or ctx.pr_number
        if rid is not None:
            return await self._provider.create_comment(identifier, int(rid), body)
        return False

    async def get_file_content(self, ctx: EventContext, path: str, ref: str | None = None) -> str | None:
        if self._provider is None:
            return None
        identifier = f"{ctx.owner}/{ctx.repo}" if ctx.owner else ctx.repo
        return await self._provider.get_file(identifier, path, ref)

    async def create_branch(self, ctx: EventContext, base: str, head: str) -> bool:
        if self._provider is None:
            return False
        identifier = f"{ctx.owner}/{ctx.repo}" if ctx.owner else ctx.repo
        return await self._provider.create_branch(identifier, head, base)

    async def create_pr(self, ctx: EventContext, title: str, body: str, head: str, base: str) -> int | None:
        if self._provider is None:
            return None
        identifier = f"{ctx.owner}/{ctx.repo}" if ctx.owner else ctx.repo
        pr = await self._provider.create_pull_request(identifier, title, head, base, body)
        return pr.id if pr else None

    async def get_pr_diff(self, ctx: EventContext, pr_number: int) -> str | None:
        if self._provider is None:
            return None
        identifier = f"{ctx.owner}/{ctx.repo}" if ctx.owner else ctx.repo
        return await self._provider.get_pull_request_diff(identifier, pr_number)

    async def set_commit_status(self, ctx: EventContext, sha: str, state: str, description: str) -> bool:
        if self._provider is None:
            return False
        identifier = f"{ctx.owner}/{ctx.repo}" if ctx.owner else ctx.repo
        return await self._provider.set_commit_status(identifier, sha, state, description)


def parse_gitlab_webhook(event_type: str, payload: dict[str, Any]) -> EventContext | None:
    ctx = parse_legacy_webhook(GitLabLegacyNormalizer(), event_type, payload)
    if ctx is not None:
        ctx.platform = "gitlab"
    return ctx


async def parse_gitlab_webhook_request(request: Request, secret: str) -> WebhookEvent:
    return await parse_webhook(GitLabWebhookNormalizer(), request, secret)
