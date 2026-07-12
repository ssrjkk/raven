from __future__ import annotations

import os
from typing import Any, cast

import httpx
from loguru import logger

from ravencode.agents.orchestrator import AgentType, Orchestrator
from ravencode.integrations.base import CIProvider
from ravencode.integrations.models import EventContext, EventType, WorkflowResult


class GitLabClient:
    """Low-level GitLab REST API client using httpx."""

    def __init__(self, token: str | None = None, api_url: str = ""):
        self._token = token or os.getenv("GITLAB_TOKEN") or ""
        base = api_url or os.getenv("CI_SERVER_URL", "https://gitlab.com/api/v4") or "https://gitlab.com/api/v4"
        self._api_url = base.rstrip("/")
        if not self._api_url.endswith("/api/v4"):
            self._api_url = f"{self._api_url}/api/v4"
        self._headers = {"User-Agent": "ravencode/1.0"}
        if self._token:
            self._headers["PRIVATE-TOKEN"] = self._token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._api_url}{path}"
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

    async def create_comment(self, project_id: int | str, mr_iid: int, body: str) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/projects/{project_id}/merge_requests/{mr_iid}/notes",
            json={"body": body},
        )
        return cast(dict[str, Any], resp.json())

    async def create_issue_note(self, project_id: int | str, issue_iid: int, body: str) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"/projects/{project_id}/issues/{issue_iid}/notes",
            json={"body": body},
        )
        return cast(dict[str, Any], resp.json())

    async def get_file(self, project_id: int | str, path: str, ref: str | None = None) -> str | None:
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref
        try:
            resp = await self._request("GET", f"/projects/{project_id}/repository/files/{path}", params=params)
            data = resp.json()
            import base64
            return base64.b64decode(data["content"]).decode("utf-8")
        except httpx.HTTPStatusError as e:
            logger.debug("GitLab get_file failed: {}", e)
            return None

    async def create_branch(self, project_id: int | str, base: str, head: str) -> bool:
        try:
            await self._request(
                "POST",
                f"/projects/{project_id}/repository/branches",
                json={"branch": head, "ref": base},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create branch: {}", e)
            return False

    async def create_mr(self, project_id: int | str, title: str, description: str, source: str, target: str) -> int | None:
        try:
            resp = await self._request(
                "POST",
                f"/projects/{project_id}/merge_requests",
                json={"title": title, "description": description, "source_branch": source, "target_branch": target},
            )
            data = cast(dict[str, Any], resp.json())
            return data.get("iid")
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create MR: {}", e)
            return None

    async def get_mr_diff(self, project_id: int | str, mr_iid: int) -> str | None:
        try:
            resp = await self._request("GET", f"/projects/{project_id}/merge_requests/{mr_iid}/changes")
            data = resp.json()
            changes = data.get("changes", [])
            lines = []
            for c in changes:
                lines.append(f"--- a/{c['old_path']}")
                lines.append(f"+++ b/{c['new_path']}")
                lines.append(c.get("diff", ""))
            return "\n".join(lines)
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to get MR diff: {}", e)
            return None

    async def get_issue(self, project_id: int | str, issue_iid: int) -> dict[str, Any]:
        resp = await self._request("GET", f"/projects/{project_id}/issues/{issue_iid}")
        return cast(dict[str, Any], resp.json())

    async def resolve_project_path(self, owner: str, repo: str) -> str:
        try:
            resp = await self._request("GET", f"/projects/{owner}%2F{repo}")
            data = resp.json()
            return str(data["id"])
        except httpx.HTTPStatusError:
            return f"{owner}%2F{repo}"


def parse_gitlab_webhook(event_type: str, payload: dict[str, Any]) -> EventContext | None:
    project = payload.get("project") or {}
    path = project.get("path_with_namespace", "")
    parts = path.split("/", 1)
    owner = parts[0] if len(parts) == 2 else ""
    repo = parts[1] if len(parts) == 2 else ""

    ctx = EventContext(
        event_type=EventType.ISSUE_COMMENT,
        platform="gitlab",
        repo=repo,
        owner=owner,
        raw=payload,
        sender=((payload.get("user") or {}).get("username")),
        ref=payload.get("ref"),
    )

    object_attrs = payload.get("object_attributes") or {}

    if event_type == "Issue Hook":
        ctx.event_type = EventType.ISSUE_OPENED
        ctx.issue_number = object_attrs.get("iid")
        ctx.title = object_attrs.get("title")
        ctx.body = object_attrs.get("description")
        ctx.sha = object_attrs.get("last_commit", {}).get("id") if isinstance(object_attrs.get("last_commit"), dict) else None

    elif event_type == "Note Hook":
        noteable = object_attrs.get("noteable_type", "")
        ctx.comment_id = object_attrs.get("id")
        ctx.comment_body = object_attrs.get("note")
        if noteable == "Issue":
            ctx.event_type = EventType.ISSUE_COMMENT
            issue = payload.get("issue") or {}
            ctx.issue_number = issue.get("iid")
            ctx.title = issue.get("title")
            ctx.body = issue.get("description")
        elif noteable == "MergeRequest":
            ctx.event_type = EventType.MERGE_REQUEST_COMMENT
            mr = payload.get("merge_request") or {}
            ctx.pr_number = mr.get("iid")
            ctx.title = mr.get("title")
            ctx.body = mr.get("description")

    elif event_type == "Merge Request Hook":
        action = object_attrs.get("action", "")
        ctx.pr_number = object_attrs.get("iid")
        ctx.title = object_attrs.get("title")
        ctx.body = object_attrs.get("description")
        if action in ("open", "opened"):
            ctx.event_type = EventType.MERGE_REQUEST_OPENED

    return ctx


GL_TRIGGER_PREFIXES = ("/ravencode", "/rc", "@ravencode")


def is_triggered(body: str | None) -> bool:
    if not body:
        return False
    stripped = body.strip().lower()
    return any(stripped.startswith(p) for p in GL_TRIGGER_PREFIXES)


class GitLabIntegration(CIProvider):
    """GitLab integration with ReActAgent-powered automation."""

    def __init__(
        self,
        token: str | None = None,
        api_url: str = "",
        orchestrator: Orchestrator | None = None,
    ):
        super().__init__(token, api_url)
        self._gl = GitLabClient(token, api_url)
        self._orch = orchestrator or Orchestrator()
        self._project_cache: dict[str, str] = {}

    async def _project_id(self, ctx: EventContext) -> str:
        key = f"{ctx.owner}/{ctx.repo}"
        if key not in self._project_cache:
            self._project_cache[key] = await self._gl.resolve_project_path(ctx.owner, ctx.repo)
        return self._project_cache[key]

    async def post_comment(self, ctx: EventContext, body: str) -> bool:
        pid = await self._project_id(ctx)
        try:
            if ctx.issue_number is not None:
                await self._gl.create_issue_note(pid, ctx.issue_number, body)
            elif ctx.pr_number is not None:
                await self._gl.create_comment(pid, ctx.pr_number, body)
            else:
                return False
            return True
        except Exception as e:
            logger.error("Failed to post comment: {}", e)
            return False

    async def get_file_content(self, ctx: EventContext, path: str, ref: str | None = None) -> str | None:
        pid = await self._project_id(ctx)
        return await self._gl.get_file(pid, path, ref)

    async def create_branch(self, ctx: EventContext, base: str, head: str) -> bool:
        pid = await self._project_id(ctx)
        return await self._gl.create_branch(pid, base, head)

    async def create_pr(self, ctx: EventContext, title: str, body: str, head: str, base: str) -> int | None:
        pid = await self._project_id(ctx)
        return await self._gl.create_mr(pid, title, body, head, base)

    async def get_pr_diff(self, ctx: EventContext, pr_number: int) -> str | None:
        pid = await self._project_id(ctx)
        return await self._gl.get_mr_diff(pid, pr_number)

    async def set_commit_status(self, ctx: EventContext, sha: str, state: str, description: str) -> bool:
        pid = await self._project_id(ctx)
        try:
            await self._gl._request(
                "POST",
                f"/projects/{pid}/statuses/{sha}",
                json={"state": state, "description": description, "context": "ravencode/ci"},
            )
            return True
        except Exception as e:
            logger.error("Failed to set commit status: {}", e)
            return False

    async def _handle_issue_comment(self, ctx: EventContext) -> WorkflowResult | None:
        if not is_triggered(ctx.comment_body):
            return None
        body = ctx.comment_body or ""
        parts = body.strip().split(None, 1)
        command = parts[1].strip() if len(parts) > 1 else "explain"

        if command == "explain":
            return await self._run_explain(ctx)
        if command == "fix":
            return await self._run_fix(ctx)
        if command == "review":
            return await self._run_review(ctx)

        await self.post_comment(ctx, "RavenCode available commands: `/ravencode explain`, `/ravencode fix`, `/ravencode review`")
        return WorkflowResult(success=True, summary="Help displayed")

    async def _run_explain(self, ctx: EventContext) -> WorkflowResult:
        pid = await self._project_id(ctx)
        if ctx.issue_number:
            issue = await self._gl.get_issue(pid, ctx.issue_number)
            prompt = f"Explain this GitLab issue:\n\nTitle: {issue.get('title', '')}\n\n{issue.get('description', '')}"
        else:
            return WorkflowResult(success=False, summary="No context")
        result = await self._orch.dispatch(prompt, AgentType.PLANNER)
        msg = result.data or "No analysis"
        await self.post_comment(ctx, f"**RavenCode Analysis**\n\n{msg}")
        return WorkflowResult(success=True, summary=msg)

    async def _run_fix(self, ctx: EventContext) -> WorkflowResult:
        if ctx.issue_number is None:
            return WorkflowResult(success=False, summary="No issue context")
        pid = await self._project_id(ctx)
        issue = await self._gl.get_issue(pid, ctx.issue_number)
        prompt = f"Implement a fix for:\n\nTitle: {issue.get('title', '')}\n\n{issue.get('description', '')}"
        result = await self._orch.dispatch(prompt, AgentType.CODER)
        if result.success:
            branch = f"ravencode/fix-{ctx.issue_number}"
            await self._gl.create_branch(pid, "main", branch)
            mr_iid = await self._gl.create_mr(
                pid,
                f"Fix: {issue.get('title', '')[:60]}",
                f"Automated fix\n\n{result.data or ''}",
                branch, "main",
            )
            msg = f"Created MR !{mr_iid}" if mr_iid else (result.data or "Done")
            await self.post_comment(ctx, f"**RavenCode Fix**\n\n{msg}")
        return WorkflowResult(success=result.success, summary=result.data or "", error=result.error)

    async def _run_review(self, ctx: EventContext) -> WorkflowResult:
        if ctx.pr_number is None:
            return WorkflowResult(success=False, summary="No MR context")
        diff = await self.get_pr_diff(ctx, ctx.pr_number)
        if not diff:
            return WorkflowResult(success=False, summary="No diff")
        prompt = f"Review this merge request:\n\n{diff}"
        result = await self._orch.dispatch(prompt, AgentType.DEBUGGER)
        review = result.data or "Review complete"
        await self.post_comment(ctx, f"## RavenCode Review\n\n{review}")
        return WorkflowResult(success=True, summary=review)

    async def _handle_pr_opened(self, ctx: EventContext) -> WorkflowResult | None:
        diff = await self.get_pr_diff(ctx, ctx.pr_number or 0)
        if not diff:
            return None
        prompt = f"Summarize this new merge request:\n\nTitle: {ctx.title}\n\n{diff}"
        result = await self._orch.dispatch(prompt, AgentType.PLANNER_READONLY)
        if result.data:
            await self.post_comment(ctx, f"## RavenCode Summary\n\n{result.data}")
        return WorkflowResult(success=True, summary="MR summary posted")
