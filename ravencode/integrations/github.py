from __future__ import annotations

import os
from typing import Any, cast

import httpx
from loguru import logger

from ravencode.agents.orchestrator import AgentType, Orchestrator
from ravencode.integrations.base import CIProvider
from ravencode.integrations.models import EventContext, EventType, WorkflowResult


class GitHubClient:
    """Low-level GitHub REST API client using httpx."""

    def __init__(self, token: str | None = None, api_url: str = "https://api.github.com"):
        self._token = token or os.getenv("GITHUB_TOKEN") or ""
        self._api_url = api_url
        self._headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ravencode/1.0",
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._api_url}{path}"
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

    async def create_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        return cast(dict[str, Any], resp.json())

    async def get_file(self, owner: str, repo: str, path: str, ref: str | None = None) -> str | None:
        params = {"ref": ref} if ref else {}
        try:
            resp = await self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)
            data = resp.json()
            import base64
            return base64.b64decode(data["content"]).decode("utf-8")
        except httpx.HTTPStatusError:
            return None

    async def create_branch(self, owner: str, repo: str, base: str, head: str) -> bool:
        try:
            base_resp = await self._request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{base}")
            sha = base_resp.json()["object"]["sha"]
            await self._request(
                "POST",
                f"/repos/{owner}/{repo}/git/refs",
                json={"ref": f"refs/heads/{head}", "sha": sha},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create branch: {}", e)
            return False

    async def create_pr(self, owner: str, repo: str, title: str, body: str, head: str, base: str) -> int | None:
        try:
            resp = await self._request(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                json={"title": title, "body": body, "head": head, "base": base},
            )
            data = cast(dict[str, Any], resp.json())
            return cast(int, data["number"])
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create PR: {}", e)
            return None

    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str | None:
        try:
            headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
            async with httpx.AsyncClient(headers=headers, timeout=30) as client:
                resp = await client.get(f"{self._api_url}/repos/{owner}/{repo}/pulls/{pr_number}")
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to get PR diff: {}", e)
            return None

    async def set_commit_status(self, owner: str, repo: str, sha: str, state: str, description: str) -> bool:
        try:
            await self._request(
                "POST",
                f"/repos/{owner}/{repo}/statuses/{sha}",
                json={"state": state, "description": description, "context": "ravencode"},
            )
            return True
        except httpx.HTTPStatusError:
            return False

    async def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")
        return cast(dict[str, Any], resp.json())

    async def close_issue(self, owner: str, repo: str, issue_number: int) -> bool:
        try:
            await self._request(
                "PATCH",
                f"/repos/{owner}/{repo}/issues/{issue_number}",
                json={"state": "closed"},
            )
            return True
        except httpx.HTTPStatusError:
            return False

    async def get_repo_labels(self, owner: str, repo: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/repos/{owner}/{repo}/labels")
        return cast(list[dict[str, Any]], resp.json())

    async def add_labels(self, owner: str, repo: str, issue_number: int, labels: list[str]) -> bool:
        try:
            await self._request(
                "POST",
                f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
                json={"labels": labels},
            )
            return True
        except httpx.HTTPStatusError:
            return False


WEBHOOK_EVENT_MAP: dict[str, EventType] = {
    "issues": EventType.ISSUE_OPENED,
    "issue_comment": EventType.ISSUE_COMMENT,
    "pull_request": EventType.PR_OPENED,
    "pull_request_review_comment": EventType.PR_COMMENT,
    "pull_request_review": EventType.PR_REVIEW_REQUESTED,
    "push": EventType.PUSH,
}


def parse_github_webhook(event_name: str, payload: dict[str, Any]) -> EventContext | None:
    gh_event = WEBHOOK_EVENT_MAP.get(event_name)
    if gh_event is None:
        return None

    repo_full = (payload.get("repository") or {}).get("full_name", "")
    parts = repo_full.split("/", 1)
    owner = parts[0] if len(parts) == 2 else ""
    repo = parts[1] if len(parts) == 2 else ""

    ctx = EventContext(
        event_type=gh_event,
        platform="github",
        repo=repo,
        owner=owner,
        raw=payload,
        sender=((payload.get("sender") or {}).get("login")),
        ref=payload.get("ref"),
        sha=(payload.get("after")),
    )

    if event_name == "issues":
        issue = payload.get("issue") or {}
        action = payload.get("action", "")
        ctx.issue_number = issue.get("number")
        ctx.title = issue.get("title")
        ctx.body = issue.get("body")
        if action == "opened":
            ctx.event_type = EventType.ISSUE_OPENED

    elif event_name == "issue_comment":
        issue = payload.get("issue") or {}
        comment = payload.get("comment") or {}
        ctx.issue_number = issue.get("number")
        ctx.comment_id = comment.get("id")
        ctx.comment_body = comment.get("body")
        ctx.title = issue.get("title")
        ctx.body = issue.get("body")
        ctx.event_type = EventType.ISSUE_COMMENT

    elif event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        action = payload.get("action", "")
        ctx.pr_number = pr.get("number")
        ctx.title = pr.get("title")
        ctx.body = pr.get("body")
        if action == "opened":
            ctx.event_type = EventType.PR_OPENED
        elif action == "review_requested":
            ctx.event_type = EventType.PR_REVIEW_REQUESTED

    elif event_name == "pull_request_review_comment":
        pr = payload.get("pull_request") or {}
        comment = payload.get("comment") or {}
        ctx.pr_number = pr.get("number")
        ctx.comment_id = comment.get("id")
        ctx.comment_body = comment.get("body")
        ctx.event_type = EventType.PR_COMMENT

    return ctx


TRIGGER_PREFIXES = ("/ravencode", "/rc", "@ravencode")


def is_triggered(body: str | None) -> bool:
    if not body:
        return False
    stripped = body.strip().lower()
    return any(stripped.startswith(p) for p in TRIGGER_PREFIXES)


_ROUTE_HELP = """I understand the following commands:

- `/ravencode explain` — explain this issue/PR
- `/ravencode fix` — implement changes and open a PR
- `/ravencode review` — review the current PR
- `/ravencode label` — suggest labels for this issue
- `/ravencode summarize` — summarize the discussion so far
- `/ravencode help` — show this message
"""


class GitHubIntegration(CIProvider):
    """Full GitHub integration with ReActAgent-powered automation."""

    def __init__(
        self,
        token: str | None = None,
        api_url: str = "https://api.github.com",
        orchestrator: Orchestrator | None = None,
    ):
        super().__init__(token, api_url)
        self._gh = GitHubClient(token, api_url)
        self._orch = orchestrator or Orchestrator()

    async def post_comment(self, ctx: EventContext, body: str) -> bool:
        num = ctx.issue_number or ctx.pr_number
        if num is None:
            return False
        try:
            await self._gh.create_comment(ctx.owner, ctx.repo, num, body)
            return True
        except Exception as e:
            logger.error("Failed to post comment: {}", e)
            return False

    async def get_file_content(self, ctx: EventContext, path: str, ref: str | None = None) -> str | None:
        return await self._gh.get_file(ctx.owner, ctx.repo, path, ref)

    async def create_branch(self, ctx: EventContext, base: str, head: str) -> bool:
        return await self._gh.create_branch(ctx.owner, ctx.repo, base, head)

    async def create_pr(self, ctx: EventContext, title: str, body: str, head: str, base: str) -> int | None:
        return await self._gh.create_pr(ctx.owner, ctx.repo, title, body, head, base)

    async def get_pr_diff(self, ctx: EventContext, pr_number: int) -> str | None:
        return await self._gh.get_pr_diff(ctx.owner, ctx.repo, pr_number)

    async def set_commit_status(self, ctx: EventContext, sha: str, state: str, description: str) -> bool:
        return await self._gh.set_commit_status(ctx.owner, ctx.repo, sha, state, description)

    async def _handle_issue_comment(self, ctx: EventContext) -> WorkflowResult | None:
        if not is_triggered(ctx.comment_body):
            return None
        body = ctx.comment_body or ""
        parts = body.strip().split(None, 1)
        command = parts[1].strip() if len(parts) > 1 else "help"

        if command == "help":
            await self.post_comment(ctx, _ROUTE_HELP)
            return WorkflowResult(success=True, summary="Displayed help message")

        if command == "summarize":
            return await self._run_summarize(ctx)

        if command == "explain":
            return await self._run_explain(ctx)

        if command.startswith("fix"):
            return await self._run_fix(ctx, command)

        if command == "review":
            return await self._run_review(ctx)

        if command == "label":
            return await self._run_label(ctx)

        await self.post_comment(ctx, _ROUTE_HELP)
        return WorkflowResult(success=True, summary="Unknown command, displayed help")

    async def _run_summarize(self, ctx: EventContext) -> WorkflowResult:
        if ctx.issue_number:
            issue = await self._gh.get_issue(ctx.owner, ctx.repo, ctx.issue_number)
            prompt = f"Summarize this GitHub issue:\n\nTitle: {issue.get('title', '')}\n\nBody:\n{issue.get('body', '')}\n\nComments: check the API for details"
        elif ctx.pr_number:
            diff = await self._gh.get_pr_diff(ctx.owner, ctx.repo, ctx.pr_number)
            prompt = f"Summarize this pull request diff:\n\n{diff or 'No diff available'}"
        else:
            return WorkflowResult(success=False, summary="No issue or PR context")
        result = await self._orch.dispatch(prompt, AgentType.AUTONOMOUS)
        summary = result.data or "No summary generated"
        await self.post_comment(ctx, f"**RavenCode Summary**\n\n{summary}")
        return WorkflowResult(success=True, summary=summary)

    async def _run_explain(self, ctx: EventContext) -> WorkflowResult:
        if ctx.issue_number:
            issue = await self._gh.get_issue(ctx.owner, ctx.repo, ctx.issue_number)
            prompt = f"Explain this GitHub issue and suggest how to approach it:\n\nTitle: {issue.get('title', '')}\n\nBody:\n{issue.get('body', '')}"
        elif ctx.pr_number:
            diff = await self._gh.get_pr_diff(ctx.owner, ctx.repo, ctx.pr_number)
            prompt = f"Review and explain this pull request:\n\n{diff or 'No diff available'}"
        else:
            return WorkflowResult(success=False, summary="No context")
        result = await self._orch.dispatch(prompt, AgentType.PLANNER)
        explanation = result.data or "No explanation"
        await self.post_comment(ctx, f"**RavenCode Analysis**\n\n{explanation}")
        return WorkflowResult(success=True, summary=explanation)

    async def _run_fix(self, ctx: EventContext, command: str) -> WorkflowResult:
        extra = command[3:].strip() if len(command) > 3 else ""
        if ctx.issue_number is None:
            return WorkflowResult(success=False, summary="No issue context")
        issue = await self._gh.get_issue(ctx.owner, ctx.repo, ctx.issue_number)
        title = issue.get("title", "")
        body_text = issue.get("body", "")
        prompt = f"Implement a fix for this GitHub issue:\n\nTitle: {title}\n\nDescription:\n{body_text}\n\n{extra}\n\nCreate the necessary changes and commit them."
        result = await self._orch.dispatch(prompt, AgentType.CODER)
        if result.success:
            branch = f"ravencode/fix-{ctx.issue_number}"
            await self._gh.create_branch(ctx.owner, ctx.repo, "main", branch)
            pr_url = await self._gh.create_pr(
                ctx.owner, ctx.repo,
                f"Fix: {title[:60]}",
                f"Automated fix for #{ctx.issue_number}\n\n{result.data or ''}",
                branch, "main",
            )
            msg = f"**RavenCode Fix** ✨\n\nCreated PR #{pr_url}" if pr_url else f"**RavenCode Fix**\n\n{result.data}"
            await self.post_comment(ctx, msg)
        else:
            await self.post_comment(ctx, f"**RavenCode Fix Failed**\n\n{result.error or 'Unknown error'}")
        return WorkflowResult(success=result.success, summary=result.data or "", error=result.error)

    async def _run_review(self, ctx: EventContext) -> WorkflowResult:
        if ctx.pr_number is None:
            return WorkflowResult(success=False, summary="No PR context")
        diff = await self._gh.get_pr_diff(ctx.owner, ctx.repo, ctx.pr_number)
        if not diff:
            return WorkflowResult(success=False, summary="Could not fetch diff")
        prompt = f"Review this pull request. Provide detailed feedback on code quality, potential bugs, and suggestions:\n\n{diff}"
        result = await self._orch.dispatch(prompt, AgentType.DEBUGGER)
        review = result.data or "Review complete"
        await self.post_comment(ctx, f"## RavenCode Review\n\n{review}")
        return WorkflowResult(success=True, summary=review)

    async def _run_label(self, ctx: EventContext) -> WorkflowResult:
        if ctx.issue_number is None:
            return WorkflowResult(success=False, summary="No issue context")
        issue = await self._gh.get_issue(ctx.owner, ctx.repo, ctx.issue_number)
        existing = [lb["name"] for lb in await self._gh.get_repo_labels(ctx.owner, ctx.repo)]
        prompt = f"Suggest 1-3 labels from {existing} for this GitHub issue:\n\nTitle: {issue.get('title', '')}\n\nBody:\n{issue.get('body', '')}\n\nReturn only the label names, one per line."
        result = await self._orch.dispatch(prompt, AgentType.PLANNER_READONLY)
        if result.data:
            lines = [lb.strip() for lb in result.data.split("\n") if lb.strip() in existing]
            if lines:
                await self._gh.add_labels(ctx.owner, ctx.repo, ctx.issue_number, lines)
                await self.post_comment(ctx, f"**RavenCode** — Added labels: {', '.join(lines)}")
        return WorkflowResult(success=True, summary="Labels suggested")

    async def _handle_pr_opened(self, ctx: EventContext) -> WorkflowResult | None:
        diff = await self._gh.get_pr_diff(ctx.owner, ctx.repo, ctx.pr_number or 0)
        if not diff:
            return None
        prompt = f"Provide a brief initial review of this new pull request:\n\nTitle: {ctx.title}\n\n{diff}"
        result = await self._orch.dispatch(prompt, AgentType.PLANNER_READONLY)
        if result.data:
            await self.post_comment(ctx, f"## RavenCode Initial Review\n\n{result.data}")
        return WorkflowResult(success=True, summary="Initial review posted")
