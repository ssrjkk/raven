from __future__ import annotations

import base64
import os
from typing import Any, cast

import httpx
from loguru import logger

from ravencode.integrations.vcs.models import Branch, PullRequest, Repository


class GitLabProvider:
    def __init__(self, token: str | None = None, api_url: str = ""):
        self._token = token or os.getenv("GITLAB_TOKEN") or ""
        base = api_url or os.getenv("CI_SERVER_URL", "https://gitlab.com/api/v4") or "https://gitlab.com/api/v4"
        self._api_url = base.rstrip("/")
        if not self._api_url.endswith("/api/v4"):
            self._api_url = f"{self._api_url}/api/v4"
        self._headers = {"User-Agent": "ravencode/1.0"}
        if self._token:
            self._headers["PRIVATE-TOKEN"] = self._token
        self._project_cache: dict[str, str] = {}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._api_url}{path}"
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            resp = await client.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp

    async def _resolve_project_id(self, owner: str, repo: str) -> str:
        key = f"{owner}/{repo}"
        if key not in self._project_cache:
            try:
                resp = await self._request("GET", f"/projects/{owner}%2F{repo}")
                data = cast(dict[str, Any], resp.json())
                self._project_cache[key] = str(data["id"])
            except httpx.HTTPStatusError:
                self._project_cache[key] = f"{owner}%2F{repo}"
        return self._project_cache[key]

    async def _ensure_id(self, identifier: str) -> str:
        if "/" in identifier:
            parts = identifier.split("/", 1)
            return await self._resolve_project_id(parts[0], parts[1])
        return identifier

    async def get_repository(self, identifier: str) -> Repository:
        pid = await self._ensure_id(identifier)
        resp = await self._request("GET", f"/projects/{pid}")
        data = cast(dict[str, Any], resp.json())
        return Repository(
            name=data["name"],
            full_name=data["path_with_namespace"],
            default_branch=data.get("default_branch", "main"),
            private=data.get("visibility", "public") == "private",
        )

    async def list_branches(self, identifier: str) -> list[Branch]:
        pid = await self._ensure_id(identifier)
        resp = await self._request("GET", f"/projects/{pid}/repository/branches")
        return [
            Branch(name=b["name"], commit_sha=b["commit"]["id"], protected=b["protected"])
            for b in cast(list[dict[str, Any]], resp.json())
        ]

    async def create_pull_request(self, identifier: str, title: str, source: str, target: str, body: str = "") -> PullRequest:
        pid = await self._ensure_id(identifier)
        resp = await self._request(
            "POST",
            f"/projects/{pid}/merge_requests",
            json={"title": title, "description": body, "source_branch": source, "target_branch": target},
        )
        data = cast(dict[str, Any], resp.json())
        return PullRequest(
            id=cast(int, data["iid"]),
            title=data["title"],
            source_branch=data["source_branch"],
            target_branch=data["target_branch"],
            url=data["web_url"],
        )

    async def get_file(self, identifier: str, path: str, ref: str | None = None) -> str | None:
        pid = await self._ensure_id(identifier)
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref
        try:
            resp = await self._request("GET", f"/projects/{pid}/repository/files/{path}", params=params)
            data = resp.json()
            return base64.b64decode(data["content"]).decode("utf-8")
        except httpx.HTTPStatusError as e:
            logger.debug("GitLab get_file failed: {}", e)
            return None

    async def create_branch(self, identifier: str, name: str, source: str) -> bool:
        pid = await self._ensure_id(identifier)
        try:
            await self._request(
                "POST",
                f"/projects/{pid}/repository/branches",
                json={"branch": name, "ref": source},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create branch: {}", e)
            return False

    async def create_comment(self, identifier: str, resource_id: int, body: str, resource_type: str = "issue") -> bool:
        pid = await self._ensure_id(identifier)
        endpoint = (
            f"/projects/{pid}/issues/{resource_id}/notes"
            if resource_type == "issue"
            else f"/projects/{pid}/merge_requests/{resource_id}/notes"
        )
        try:
            await self._request("POST", endpoint, json={"body": body})
            return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create comment: {}", e)
            return False

    async def get_pull_request_diff(self, identifier: str, pr_number: int) -> str | None:
        pid = await self._ensure_id(identifier)
        try:
            resp = await self._request("GET", f"/projects/{pid}/merge_requests/{pr_number}/changes")
            data = cast(dict[str, Any], resp.json())
            changes = cast(list[dict[str, Any]], data.get("changes", []))
            lines = []
            for c in changes:
                old = c.get("old_path", "")
                new = c.get("new_path", "")
                diff = c.get("diff", "")
                lines.append(f"--- a/{old}")
                lines.append(f"+++ b/{new}")
                lines.append(diff)
            return "\n".join(lines)
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to get MR diff: {}", e)
            return None

    async def set_commit_status(self, identifier: str, sha: str, state: str, description: str, context: str = "ravencode/ci") -> bool:
        pid = await self._ensure_id(identifier)
        try:
            await self._request(
                "POST",
                f"/projects/{pid}/statuses/{sha}",
                json={"state": state, "description": description, "context": context},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.debug("GitLab set_commit_status failed: {}", e)
            return False

    async def get_issue(self, identifier: str, issue_iid: int) -> dict[str, Any]:
        pid = await self._ensure_id(identifier)
        resp = await self._request("GET", f"/projects/{pid}/issues/{issue_iid}")
        return cast(dict[str, Any], resp.json())
