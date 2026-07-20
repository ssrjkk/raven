from __future__ import annotations

from pathlib import Path
from typing import Any

from raven.coding.git_integration import GitIntegration
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


def _get_git() -> GitIntegration:
    return GitIntegration()


def git_status(workspace: str = "") -> dict[str, Any]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    return git.status()


def git_branch(workspace: str = "") -> dict[str, Any]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    return {"branch": git.get_branch(), "is_branch": git.is_branch(), "is_repo": git.is_repo()}


def git_log(count: int = 10, workspace: str = "") -> list[dict[str, str]]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    return git.get_log(count)


def git_diff(staged: bool = False, workspace: str = "") -> str:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    return git.get_diff(staged=staged)


async def git_commit(message: str = "", auto: bool = False, workspace: str = "") -> dict[str, Any]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    if auto:
        result = await git.auto_commit_async()
    else:
        result = git.commit(message or "auto: commit")
    return {"success": result.success, "message": result.message, "commit_hash": result.commit_hash, "error": result.error}


def git_push(workspace: str = "") -> str:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    stdout, stderr = git._run("push")
    return stderr or stdout or "pushed"


def git_pull(workspace: str = "") -> str:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    stdout, stderr = git._run("pull")
    return stderr or stdout or "pulled"


def git_branches(workspace: str = "") -> list[str]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    stdout, _ = git._run("branch", "-a")
    return [b.strip() for b in stdout.split("\n") if b.strip()]


def git_checkout(branch: str, create: bool = False, workspace: str = "") -> str:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    args = ["checkout"]
    if create:
        args += ["-b"]
    args.append(branch)
    stdout, stderr = git._run(*args)
    return stderr or stdout or f"switched to {branch}"


async def git_create_pr(title: str = "", body: str = "", workspace: str = "") -> dict[str, Any]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    result = await git.create_pr_async(title=title, body=body)
    return {"success": result.success, "url": result.url, "error": result.error}


async def git_review(file_path: str = "", workspace: str = "") -> dict[str, Any]:
    git = _get_git()
    if workspace:
        git._repo = Path(workspace).resolve()
    result = await git.llm_review(file_path or None)
    return {
        "summary": result.summary,
        "comments": [{"file": c.file, "line": c.line, "severity": c.severity, "message": c.message} for c in result.comments],
    }


def register_git_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(name="git_status", description="Show working tree status", parameters={"workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_status, category="coding"))
    registry.register(ToolSpec(name="git_branch", description="Show current branch name", parameters={"workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_branch, category="coding"))
    registry.register(ToolSpec(name="git_log", description="Show commit log", parameters={"count": {"type": "integer", "description": "Number of commits", "required": False}, "workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_log, category="coding"))
    registry.register(ToolSpec(name="git_diff", description="Show unstaged or staged diff", parameters={"staged": {"type": "boolean", "description": "Show staged diff", "required": False}, "workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_diff, category="coding"))
    registry.register(ToolSpec(name="git_commit", description="Commit staged changes", parameters={"message": {"type": "string", "description": "Commit message", "required": False}, "auto": {"type": "boolean", "description": "Auto-generate message with LLM", "required": False}, "workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_commit, category="coding"))
    registry.register(ToolSpec(name="git_push", description="Push to remote", parameters={"workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_push, category="coding"))
    registry.register(ToolSpec(name="git_pull", description="Pull from remote", parameters={"workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_pull, category="coding"))
    registry.register(ToolSpec(name="git_branches", description="List all branches", parameters={"workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_branches, category="coding"))
    registry.register(ToolSpec(name="git_checkout", description="Switch or create branch", parameters={"branch": {"type": "string", "description": "Branch name", "required": True}, "create": {"type": "boolean", "description": "Create new branch", "required": False}, "workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_checkout, category="coding"))
    registry.register(ToolSpec(name="git_create_pr", description="Create a pull request from current branch", parameters={"title": {"type": "string", "description": "PR title", "required": False}, "body": {"type": "string", "description": "PR body", "required": False}, "workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_create_pr, category="coding"))
    registry.register(ToolSpec(name="git_review", description="LLM-powered code review of unstaged changes", parameters={"file_path": {"type": "string", "description": "Specific file to review", "required": False}, "workspace": {"type": "string", "description": "Optional workspace path", "required": False}}, handler=git_review, category="coding"))
