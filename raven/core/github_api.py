from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from raven.core.config import settings
from raven.core.secrets import secrets


class CreatePRRequest(BaseModel):
    owner: str = Field(..., max_length=100)
    repo: str = Field(..., max_length=100)
    title: str = Field(..., max_length=256)
    body: str = Field(default="", max_length=65536)
    head: str = Field(default="main", max_length=100)
    base: str = Field(default="main", max_length=100)


class CreateIssueRequest(BaseModel):
    owner: str = Field(..., max_length=100)
    repo: str = Field(..., max_length=100)
    title: str = Field(..., max_length=256)
    body: str = Field(default="", max_length=65536)
    labels: list[str] = Field(default_factory=list, max_length=100)


class WorkflowDispatchRequest(BaseModel):
    owner: str = Field(..., max_length=100)
    repo: str = Field(..., max_length=100)
    workflow_id: str = Field(..., max_length=100)
    ref: str = Field(default="main", max_length=100)
    inputs: dict[str, str] = Field(default_factory=dict, max_length=50)


class CreateReviewRequest(BaseModel):
    owner: str = Field(..., max_length=100)
    repo: str = Field(..., max_length=100)
    pull_number: int = Field(..., ge=0)
    body: str = Field(default="", max_length=65536)
    event: str = Field(default="COMMENT", max_length=20)
    commit_id: str = Field(default="", max_length=40)


class MergePRRequest(BaseModel):
    owner: str = Field(..., max_length=100)
    repo: str = Field(..., max_length=100)
    pull_number: int = Field(..., ge=0)
    commit_title: str = Field(default="", max_length=256)
    commit_message: str = Field(default="", max_length=65536)
    merge_method: str = Field(default="merge", max_length=10)


class CloneRepoRequest(BaseModel):
    owner: str = Field(..., max_length=100)
    repo: str = Field(..., max_length=100)
    branch: str = "main"
    target_dir: str = ""


class CodeSearchRequest(BaseModel):
    owner: str
    repo: str
    query: str
    page: int = 1
    per_page: int = 10


class SetTokenRequest(BaseModel):
    token: str


def _resolve_token() -> str:
    token = settings.github_token.get_secret_value() or ""
    if not token:
        token = secrets.get("github_oauth_token", "")
    return token


def _client() -> httpx.AsyncClient:
    token = _resolve_token()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "raven-ai/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(headers=headers, timeout=30)


async def _get(owner: str, repo: str | None, path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"https://api.github.com/repos/{owner}/{repo}/{path}" if repo else f"https://api.github.com/{path}"
    async with _client() as c:
        resp = await c.get(url, params=params)
        if resp.status_code == 404:
            raise HTTPException(404, "Not found")
        if resp.status_code == 403:
            raise HTTPException(403, "Rate limited or insufficient permissions")
        resp.raise_for_status()
        return resp.json()


async def _post(url_path: str, body: dict[str, Any]) -> Any:
    async with _client() as c:
        resp = await c.post(f"https://api.github.com{url_path}", json=body)
        if not resp.is_success:
            detail = resp.text[:200]
            raise HTTPException(resp.status_code, f"GitHub API error: {detail}")
        return resp.json()


def create_github_router() -> APIRouter:
    router = APIRouter(prefix="/api/github", tags=["github"])

    @router.get("/user")
    async def github_user():
        token = _resolve_token()
        if not token:
            raise HTTPException(401, "GitHub token not configured")
        async with _client() as c:
            resp = await c.get("https://api.github.com/user")
            resp.raise_for_status()
            return resp.json()

    @router.get("/repos")
    async def list_repos(page: int = 1, per_page: int = 30, sort: str = "updated"):
        token = _resolve_token()
        if not token:
            raise HTTPException(401, "GitHub token not configured")
        async with _client() as c:
            resp = await c.get(
                "https://api.github.com/user/repos",
                params={"page": page, "per_page": per_page, "sort": sort, "type": "owner"},
            )
            resp.raise_for_status()
            return resp.json()

    @router.get("/repos/{owner}/{repo}")
    async def get_repo(owner: str, repo: str):
        return await _get(owner, repo, "")

    @router.get("/repos/{owner}/{repo}/branches")
    async def list_branches(owner: str, repo: str):
        return await _get(owner, repo, "branches")

    @router.get("/repos/{owner}/{repo}/contents/tree")
    async def get_file_tree(owner: str, repo: str, ref: str = "main"):
        token = _resolve_token()
        if not token:
            raise HTTPException(401, "GitHub token not configured")
        tree: list[dict[str, Any]] = []

        async def fetch_tree(path: str = "") -> None:
            async with _client() as c:
                url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
                resp = await c.get(url, params={"ref": ref})
                if resp.status_code != 200:
                    return
                items = resp.json()
                if not isinstance(items, list):
                    return
                for item in items:
                    entry: dict[str, Any] = {
                        "name": item["name"],
                        "path": item["path"],
                        "type": item["type"],
                        "size": item.get("size", 0),
                    }
                    tree.append(entry)
                    if item["type"] == "dir":
                        await fetch_tree(item["path"])

        await fetch_tree()
        return tree

    @router.get("/repos/{owner}/{repo}/contents/{path:path}")
    async def get_contents(owner: str, repo: str, path: str = "", ref: str | None = None):
        params = {"ref": ref} if ref else {}
        return await _get(owner, repo, f"contents/{path}", params=params)

    @router.get("/repos/{owner}/{repo}/pulls")
    async def list_pulls(owner: str, repo: str, state: str = "open"):
        return await _get(owner, repo, "pulls", params={"state": state, "sort": "updated", "direction": "desc"})

    @router.get("/repos/{owner}/{repo}/pulls/{number}")
    async def get_pull(owner: str, repo: str, number: int):
        return await _get(owner, repo, f"pulls/{number}")

    @router.get("/repos/{owner}/{repo}/pulls/{number}/files")
    async def get_pull_files(owner: str, repo: str, number: int):
        return await _get(owner, repo, f"pulls/{number}/files")

    @router.get("/repos/{owner}/{repo}/issues")
    async def list_issues(owner: str, repo: str, state: str = "open"):
        return await _get(owner, repo, "issues", params={"state": state, "sort": "updated", "direction": "desc"})

    @router.post("/repos/{owner}/{repo}/pulls")
    async def create_pr(body: CreatePRRequest):
        result = await _post(
            f"/repos/{body.owner}/{body.repo}/pulls",
            {
                "title": body.title,
                "body": body.body,
                "head": body.head,
                "base": body.base,
            },
        )
        logger.info("Created PR #{} in {}/{}", result.get("number"), body.owner, body.repo)
        return result

    @router.post("/repos/{owner}/{repo}/issues")
    async def create_issue(body: CreateIssueRequest):
        payload: dict[str, Any] = {"title": body.title, "body": body.body}
        if body.labels:
            payload["labels"] = body.labels
        result = await _post(f"/repos/{body.owner}/{body.repo}/issues", payload)
        logger.info("Created issue #{} in {}/{}", result.get("number"), body.owner, body.repo)
        return result

    @router.post("/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches")
    async def trigger_workflow(owner: str, repo: str, workflow_id: str, body: WorkflowDispatchRequest):
        async with _client() as c:
            url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
            resp = await c.post(url, json={"ref": body.ref, "inputs": body.inputs})
            if not resp.is_success:
                detail = resp.text[:200]
                raise HTTPException(resp.status_code, f"Workflow dispatch failed: {detail}")
            return {"ok": True, "status": resp.status_code}

    @router.get("/search/repos")
    async def search_repos(q: str, page: int = 1, per_page: int = 10):
        token = _resolve_token()
        if not token:
            raise HTTPException(401, "GitHub token not configured")
        async with _client() as c:
            resp = await c.get(
                "https://api.github.com/search/repositories", params={"q": q, "page": page, "per_page": per_page}
            )
            resp.raise_for_status()
            return resp.json()

    @router.get("/rate-limit")
    async def rate_limit():
        async with _client() as c:
            resp = await c.get("https://api.github.com/rate_limit")
            resp.raise_for_status()
            return resp.json()

    @router.post("/repos/{owner}/{repo}/clone")
    async def clone_repo(owner: str, repo: str, body: CloneRepoRequest):
        token = _resolve_token()
        if not token:
            raise HTTPException(401, "GitHub token not configured")
        repo_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        base_dir = Path(body.target_dir) if body.target_dir else Path("workspace") / "cloned"
        base = settings.resolved_workspace or Path.cwd()
        base_str = os.path.abspath(str(base))  # noqa: PTH100
        combined = str(base_dir / owner / repo)
        resolved = os.path.abspath(os.path.normpath(os.path.expanduser(combined)))  # noqa: PTH100, PTH111
        if not resolved.startswith(base_str):
            raise HTTPException(403, f"Access denied: {body.target_dir}")
        if resolved != base_str and not resolved.startswith(base_str + os.sep):
            raise HTTPException(403, f"Access denied: {body.target_dir}")
        target = Path(resolved)
        if target.exists():
            return {"ok": True, "path": str(target), "existing": True}
        target.mkdir(parents=True, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--branch",
                body.branch,
                "--depth",
                "1",
                repo_url,
                str(target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err = stderr.decode()[:500]
                if token:
                    err = err.replace(token, "***")
                raise HTTPException(500, f"Clone failed: {err}")
            logger.info("Cloned {}/{} -> {}", owner, repo, target)
            return {"ok": True, "path": str(target)}
        except FileNotFoundError:
            raise HTTPException(500, "Git not found on system") from None

    @router.post("/repos/{owner}/{repo}/pulls/{number}/merge")
    async def merge_pr(owner: str, repo: str, number: int, body: MergePRRequest):
        async with _client() as c:
            payload: dict[str, Any] = {"merge_method": body.merge_method}
            if body.commit_title:
                payload["commit_title"] = body.commit_title
            if body.commit_message:
                payload["commit_message"] = body.commit_message
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge"
            resp = await c.put(url, json=payload)
            if not resp.is_success:
                detail = resp.text[:300]
                raise HTTPException(resp.status_code, f"Merge failed: {detail}")
            data = resp.json()
            logger.info("Merged PR #{} in {}/{}", number, owner, repo)
            return data

    @router.post("/repos/{owner}/{repo}/pulls/{number}/reviews")
    async def create_review(owner: str, repo: str, number: int, body: CreateReviewRequest):
        async with _client() as c:
            payload: dict[str, Any] = {"body": body.body, "event": body.event}
            if body.commit_id:
                payload["commit_id"] = body.commit_id
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews"
            resp = await c.post(url, json=payload)
            if not resp.is_success:
                detail = resp.text[:200]
                raise HTTPException(resp.status_code, f"Review failed: {detail}")
            data = resp.json()
            logger.info("Submitted review on PR #{} in {}/{}", number, owner, repo)
            return data

    @router.get("/repos/{owner}/{repo}/pulls/{number}/reviews")
    async def list_reviews(owner: str, repo: str, number: int):
        return await _get(owner, repo, f"pulls/{number}/reviews")

    @router.get("/repos/{owner}/{repo}/issues/{number}/comments")
    async def list_issue_comments(owner: str, repo: str, number: int):
        return await _get(owner, repo, f"issues/{number}/comments")

    @router.post("/repos/{owner}/{repo}/issues/{number}/comments")
    async def create_issue_comment(owner: str, repo: str, number: int, body: dict[str, str]):
        result = await _post(f"/repos/{owner}/{repo}/issues/{number}/comments", {"body": body.get("body", "")})
        logger.info("Created comment on #{}/{}", number, f"{owner}/{repo}")
        return result

    @router.get("/repos/{owner}/{repo}/search/code")
    async def search_code(owner: str, repo: str, q: str, page: int = 1, per_page: int = 10):
        token = _resolve_token()
        if not token:
            raise HTTPException(401, "GitHub token not configured")
        query = f"repo:{owner}/{repo} {q}"
        async with _client() as c:
            resp = await c.get(
                "https://api.github.com/search/code", params={"q": query, "page": page, "per_page": per_page}
            )
            if resp.status_code == 403:
                raise HTTPException(403, "Code search requires a GitHub token with repo scope")
            resp.raise_for_status()
            return resp.json()

    @router.get("/token/status")
    async def token_status():
        env_token = bool(settings.github_token.get_secret_value())
        oauth_token = bool(secrets.get("github_oauth_token", ""))
        return {
            "has_env_token": env_token,
            "has_oauth_token": oauth_token,
            "configured": env_token or oauth_token,
        }

    @router.post("/token")
    async def set_github_token(body: SetTokenRequest):
        if not body.token.strip():
            raise HTTPException(400, "Token cannot be empty")
        await secrets.set("github_oauth_token", body.token.strip())
        logger.info("GitHub OAuth token updated via API")
        return {"ok": True}

    return router
