from __future__ import annotations

from typing import Any

from loguru import logger

from raven.core.config import settings
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def _github_api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    import httpx
    token = settings.github_token or ""
    if not token:
        return {"error": "GitHub token not configured. Set GITHUB_TOKEN in .env"}
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "raven-ai/1.0",
        "Authorization": f"Bearer {token}",
    }
    url = f"https://api.github.com{path}"
    async with httpx.AsyncClient(headers=headers, timeout=30) as c:
        if method == "GET":
            resp = await c.get(url)
        else:
            resp = await c.request(method, url, json=body or {})
        if resp.status_code == 401:
            return {"error": "GitHub token invalid or expired"}
        if not resp.is_success:
            return {"error": f"GitHub API {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        return data if isinstance(data, list) else dict(data)


async def github_list_repos(page: int = 1, per_page: int = 10, sort: str = "updated") -> dict[str, Any] | list[Any]:
    """List GitHub repositories accessible to the configured token"""
    return await _github_api("GET", f"/user/repos?page={page}&per_page={per_page}&sort={sort}&type=owner")


async def github_get_repo(owner: str, repo: str) -> dict[str, Any] | list[Any]:
    """Get details for a specific GitHub repository"""
    return await _github_api("GET", f"/repos/{owner}/{repo}")


async def github_list_branches(owner: str, repo: str) -> dict[str, Any] | list[Any]:
    """List branches in a GitHub repository"""
    return await _github_api("GET", f"/repos/{owner}/{repo}/branches")


async def github_list_pulls(owner: str, repo: str, state: str = "open") -> dict[str, Any] | list[Any]:
    """List pull requests in a GitHub repository"""
    return await _github_api("GET", f"/repos/{owner}/{repo}/pulls?state={state}&sort=updated&direction=desc")


async def github_get_file(owner: str, repo: str, path: str, ref: str | None = None) -> dict[str, Any] | list[Any]:
    """Get file contents from a GitHub repository"""
    url = f"/repos/{owner}/{repo}/contents/{path}"
    if ref:
        url += f"?ref={ref}"
    return await _github_api("GET", url)


async def github_create_pr(owner: str, repo: str, title: str, body: str = "", head: str = "main", base: str = "main") -> dict[str, Any] | list[Any]:
    """Create a pull request on GitHub"""
    result = await _github_api("POST", f"/repos/{owner}/{repo}/pulls", {
        "title": title, "body": body, "head": head, "base": base,
    })
    if isinstance(result, dict) and "number" in result:
        logger.info("Created PR #{} in {}/{}", result["number"], owner, repo)
    return result


async def github_create_issue(owner: str, repo: str, title: str, body: str = "", labels: list[str] | None = None) -> dict[str, Any] | list[Any]:
    """Create an issue on GitHub"""
    payload: dict[str, Any] = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    result = await _github_api("POST", f"/repos/{owner}/{repo}/issues", payload)
    if isinstance(result, dict) and "number" in result:
        logger.info("Created issue #{} in {}/{}", result["number"], owner, repo)
    return result


async def github_search_repos(query: str, page: int = 1, per_page: int = 10) -> dict[str, Any] | list[Any]:
    """Search GitHub repositories"""
    return await _github_api("GET", f"/search/repositories?q={query}&page={page}&per_page={per_page}")


async def github_get_pr_files(owner: str, repo: str, number: int) -> dict[str, Any] | list[Any]:
    """Get files changed in a pull request"""
    return await _github_api("GET", f"/repos/{owner}/{repo}/pulls/{number}/files")


async def github_trigger_workflow(owner: str, repo: str, workflow_id: str, ref: str = "main", inputs: dict[str, str] | None = None) -> dict[str, Any] | list[Any]:
    """Trigger a GitHub Actions workflow"""
    import httpx
    token = settings.github_token or ""
    if not token:
        return {"error": "GitHub token not configured"}
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "raven-ai/1.0",
        "Authorization": f"Bearer {token}",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
    async with httpx.AsyncClient(headers=headers, timeout=30) as c:
        resp = await c.post(url, json={"ref": ref, "inputs": inputs or {}})
        if resp.status_code == 204:
            return {"ok": True, "message": f"Workflow {workflow_id} dispatched on {ref}"}
        return {"error": f"GitHub API {resp.status_code}: {resp.text[:200]}"}


async def github_merge_pr(owner: str, repo: str, number: int, merge_method: str = "merge") -> dict[str, Any] | list[Any]:
    """Merge a pull request on GitHub"""
    import httpx
    token = settings.github_token or ""
    if not token:
        token = _resolve_oauth_token()
    if not token:
        return {"error": "GitHub token not configured"}
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "raven-ai/1.0",
        "Authorization": f"Bearer {token}",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/merge"
    async with httpx.AsyncClient(headers=headers, timeout=30) as c:
        resp = await c.put(url, json={"merge_method": merge_method})
        if not resp.is_success:
            return {"error": f"Merge failed: {resp.text[:200]}"}
        data = resp.json()
        logger.info("Merged PR #{} in {}/{}", number, owner, repo)
        return dict(data)


async def github_create_review(owner: str, repo: str, number: int, body: str = "", event: str = "COMMENT") -> dict[str, Any] | list[Any]:
    """Submit a review on a pull request"""
    import httpx
    token = settings.github_token or ""
    if not token:
        token = _resolve_oauth_token()
    if not token:
        return {"error": "GitHub token not configured"}
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "raven-ai/1.0",
        "Authorization": f"Bearer {token}",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews"
    async with httpx.AsyncClient(headers=headers, timeout=30) as c:
        resp = await c.post(url, json={"body": body, "event": event})
        if not resp.is_success:
            return {"error": f"Review failed: {resp.text[:200]}"}
        data = resp.json()
        logger.info("Submitted review on PR #{} in {}/{}", number, owner, repo)
        return dict(data)


async def github_list_comments(owner: str, repo: str, number: int) -> dict[str, Any] | list[Any]:
    """List comments on an issue or pull request"""
    return await _github_api("GET", f"/repos/{owner}/{repo}/issues/{number}/comments")


async def github_create_comment(owner: str, repo: str, number: int, body: str) -> dict[str, Any] | list[Any]:
    """Add a comment to an issue or pull request"""
    return await _github_api("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", {"body": body})


async def github_search_code(owner: str, repo: str, query: str, page: int = 1, per_page: int = 10) -> dict[str, Any] | list[Any]:
    """Search code within a GitHub repository"""
    return await _github_api("GET", f"/search/code?q=repo:{owner}/{repo}+{query}&page={page}&per_page={per_page}")


async def github_clone_repo(owner: str, repo: str, branch: str = "main") -> dict[str, Any] | list[Any]:
    """Clone a GitHub repository locally"""
    import asyncio
    from pathlib import Path

    token = settings.github_token or ""
    if not token:
        token = _resolve_oauth_token()
    if not token:
        return {"error": "GitHub token not configured"}
    repo_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    target = Path("workspace") / "cloned" / owner / repo
    if target.exists():
        return {"ok": True, "path": str(target), "existing": True}
    target.mkdir(parents=True, exist_ok=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--branch", branch, "--depth", "1",
            repo_url, str(target),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return {"error": f"Clone failed: {stderr.decode()[:500]}"}
        logger.info("Cloned {}/{} -> {}", owner, repo, target)
        return {"ok": True, "path": str(target)}
    except FileNotFoundError:
        return {"error": "Git not found on system"}


def _resolve_oauth_token() -> str:
    try:
        from raven.core.secrets import secrets
        return secrets.get("github_oauth_token", "")
    except Exception:
        return ""


def register_github_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(name="github_list_repos", description="List GitHub repositories for the authenticated user", parameters={
        "page": {"type": "integer", "description": "Page number", "default": 1},
        "per_page": {"type": "integer", "description": "Results per page", "default": 10},
        "sort": {"type": "string", "description": "Sort: updated, created, pushed, full_name", "default": "updated"},
    }, handler=github_list_repos, category="github"))
    registry.register(ToolSpec(name="github_get_repo", description="Get details of a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
    }, handler=github_get_repo, category="github"))
    registry.register(ToolSpec(name="github_list_branches", description="List branches of a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
    }, handler=github_list_branches, category="github"))
    registry.register(ToolSpec(name="github_list_pulls", description="List pull requests of a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "state": {"type": "string", "description": "PR state: open, closed, all", "default": "open"},
    }, handler=github_list_pulls, category="github"))
    registry.register(ToolSpec(name="github_get_file", description="Get contents of a file from a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "path": {"type": "string", "description": "File path", "required": True},
        "ref": {"type": "string", "description": "Branch/ref (default: default branch)", "required": False},
    }, handler=github_get_file, category="github"))
    registry.register(ToolSpec(name="github_create_pr", description="Create a pull request on a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "title": {"type": "string", "description": "PR title", "required": True},
        "body": {"type": "string", "description": "PR body", "default": ""},
        "head": {"type": "string", "description": "Head branch", "default": "main"},
        "base": {"type": "string", "description": "Base branch", "default": "main"},
    }, handler=github_create_pr, category="github"))
    registry.register(ToolSpec(name="github_create_issue", description="Create an issue on a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "title": {"type": "string", "description": "Issue title", "required": True},
        "body": {"type": "string", "description": "Issue body", "default": ""},
        "labels": {"type": "array", "description": "Labels to apply", "default": None},
    }, handler=github_create_issue, category="github"))
    registry.register(ToolSpec(name="github_search_repos", description="Search GitHub repositories", parameters={
        "query": {"type": "string", "description": "Search query", "required": True},
        "page": {"type": "integer", "description": "Page number", "default": 1},
        "per_page": {"type": "integer", "description": "Results per page", "default": 10},
    }, handler=github_search_repos, category="github"))
    registry.register(ToolSpec(name="github_get_pr_files", description="Get files changed in a pull request", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "number": {"type": "integer", "description": "PR number", "required": True},
    }, handler=github_get_pr_files, category="github"))
    registry.register(ToolSpec(name="github_trigger_workflow", description="Trigger a GitHub Actions workflow dispatch", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "workflow_id": {"type": "string", "description": "Workflow ID or filename", "required": True},
        "ref": {"type": "string", "description": "Branch to run on", "default": "main"},
        "inputs": {"type": "object", "description": "Workflow inputs as JSON object", "default": None},
    }, handler=github_trigger_workflow, category="github"))
    registry.register(ToolSpec(name="github_merge_pr", description="Merge a pull request on GitHub", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "number": {"type": "integer", "description": "PR number", "required": True},
        "merge_method": {"type": "string", "description": "Merge method: merge, squash, rebase", "default": "merge"},
    }, handler=github_merge_pr, category="github"))
    registry.register(ToolSpec(name="github_create_review", description="Submit a review on a pull request", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "number": {"type": "integer", "description": "PR number", "required": True},
        "body": {"type": "string", "description": "Review body", "default": ""},
        "event": {"type": "string", "description": "Review event: APPROVE, REQUEST_CHANGES, COMMENT", "default": "COMMENT"},
    }, handler=github_create_review, category="github"))
    registry.register(ToolSpec(name="github_list_comments", description="List comments on an issue or pull request", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "number": {"type": "integer", "description": "Issue/PR number", "required": True},
    }, handler=github_list_comments, category="github"))
    registry.register(ToolSpec(name="github_create_comment", description="Add a comment to an issue or pull request", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "number": {"type": "integer", "description": "Issue/PR number", "required": True},
        "body": {"type": "string", "description": "Comment body", "required": True},
    }, handler=github_create_comment, category="github"))
    registry.register(ToolSpec(name="github_search_code", description="Search code within a GitHub repository", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "query": {"type": "string", "description": "Search query", "required": True},
        "page": {"type": "integer", "description": "Page number", "default": 1},
        "per_page": {"type": "integer", "description": "Results per page", "default": 10},
    }, handler=github_search_code, category="github"))
    registry.register(ToolSpec(name="github_clone_repo", description="Clone a GitHub repository locally", parameters={
        "owner": {"type": "string", "description": "Repository owner", "required": True},
        "repo": {"type": "string", "description": "Repository name", "required": True},
        "branch": {"type": "string", "description": "Branch to clone", "default": "main"},
    }, handler=github_clone_repo, category="github"))
