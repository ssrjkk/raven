from __future__ import annotations

import base64
import os
from typing import Any, cast

import httpx
from loguru import logger

from ravencode.integrations.vcs.models import Branch, PullRequest, Repository


class GitHubProvider:
    def __init__(self, token: str | None = None, api_url: str = "https://api.github.com"):
        self._token = token or os.getenv("GITHUB_TOKEN") or ""
        self._api_url = api_url.rstrip("/")
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

    async def get_repository(self, identifier: str) -> Repository:
        resp = await self._request("GET", f"/repos/{identifier}")
        data = cast(dict[str, Any], resp.json())
        return Repository(
            name=data["name"],
            full_name=data["full_name"],
            default_branch=data["default_branch"],
            private=data["private"],
        )

    async def list_branches(self, identifier: str) -> list[Branch]:
        resp = await self._request("GET", f"/repos/{identifier}/branches")
        return [
            Branch(name=b["name"], commit_sha=b["commit"]["sha"], protected=b["protected"])
            for b in cast(list[dict[str, Any]], resp.json())
        ]

    async def create_pull_request(self, identifier: str, title: str, source: str, target: str, body: str = "") -> PullRequest:
        resp = await self._request(
            "POST",
            f"/repos/{identifier}/pulls",
            json={"title": title, "body": body, "head": source, "base": target},
        )
        data = cast(dict[str, Any], resp.json())
        return PullRequest(
            id=cast(int, data["number"]),
            title=data["title"],
            source_branch=data["head"]["ref"],
            target_branch=data["base"]["ref"],
            url=data["html_url"],
            body=data.get("body", ""),
            state=data.get("state", "open"),
        )

    async def get_file(self, identifier: str, path: str, ref: str | None = None) -> str | None:
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref
        try:
            resp = await self._request("GET", f"/repos/{identifier}/contents/{path}", params=params)
            data = resp.json()
            return base64.b64decode(data["content"]).decode("utf-8")
        except httpx.HTTPStatusError as e:
            logger.debug("GitHub get_file failed: {}", e)
            return None

    async def create_branch(self, identifier: str, name: str, source: str) -> bool:
        try:
            base_resp = await self._request("GET", f"/repos/{identifier}/git/ref/heads/{source}")
            sha = base_resp.json()["object"]["sha"]
            await self._request(
                "POST",
                f"/repos/{identifier}/git/refs",
                json={"ref": f"refs/heads/{name}", "sha": sha},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create branch: {}", e)
            return False

    async def create_comment(self, identifier: str, resource_id: int, body: str, resource_type: str = "issue") -> bool:
        endpoint = f"/repos/{identifier}/issues/{resource_id}/comments"
        try:
            await self._request("POST", endpoint, json={"body": body})
            return True
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to create comment: {}", e)
            return False

    async def get_pull_request_diff(self, identifier: str, pr_number: int) -> str | None:
        headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
        try:
            async with httpx.AsyncClient(headers=headers, timeout=30) as client:
                resp = await client.get(f"{self._api_url}/repos/{identifier}/pulls/{pr_number}")
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as e:
            logger.warning("Failed to get PR diff: {}", e)
            return None

    async def set_commit_status(self, identifier: str, sha: str, state: str, description: str, context: str = "ravencode/ci") -> bool:
        try:
            await self._request(
                "POST",
                f"/repos/{identifier}/statuses/{sha}",
                json={"state": state, "description": description, "context": context},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.debug("GitHub set_commit_status failed: {}", e)
            return False

    async def get_issue(self, identifier: str, issue_number: int) -> dict[str, Any]:
        resp = await self._request("GET", f"/repos/{identifier}/issues/{issue_number}")
        return cast(dict[str, Any], resp.json())

    async def close_issue(self, identifier: str, issue_number: int) -> bool:
        try:
            await self._request("PATCH", f"/repos/{identifier}/issues/{issue_number}", json={"state": "closed"})
            return True
        except httpx.HTTPStatusError as e:
            logger.debug("GitHub close_issue failed: {}", e)
            return False

    async def get_repo_labels(self, identifier: str) -> list[str]:
        resp = await self._request("GET", f"/repos/{identifier}/labels")
        return [lb["name"] for lb in cast(list[dict[str, Any]], resp.json())]

    async def add_labels(self, identifier: str, issue_number: int, labels: list[str]) -> bool:
        try:
            await self._request(
                "POST",
                f"/repos/{identifier}/issues/{issue_number}/labels",
                json={"labels": labels},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.debug("GitHub add_labels failed: {}", e)
            return False
