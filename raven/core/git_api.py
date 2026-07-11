from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from raven.coding.git_integration import GitIntegration


def create_git_router() -> APIRouter:
    router = APIRouter(prefix="/api/git", tags=["git"])

    def _git(repo: str = "") -> GitIntegration:
        git = GitIntegration()
        if repo:
            git._repo = Path(repo).resolve()
        return git

    @router.get("/status")
    async def git_status(repo: str = ""):
        return _git(repo).status()

    @router.get("/branch")
    async def git_branch(repo: str = ""):
        git = _git(repo)
        return {"branch": git.get_branch(), "is_branch": git.is_branch(), "is_repo": git.is_repo()}

    @router.get("/branches")
    async def git_branches(repo: str = ""):
        git = _git(repo)
        stdout, _ = git._run("branch", "-a")
        branches = [b.replace("*", "").strip() for b in stdout.split("\n") if b.strip()]
        current = git.get_branch()
        return {"branches": branches, "current": current}

    @router.get("/log")
    async def git_log(count: int = 10, repo: str = ""):
        return _git(repo).get_log(count)

    @router.get("/diff")
    async def git_diff(staged: bool = False, repo: str = ""):
        return {"diff": _git(repo).get_diff(staged=staged)}

    @router.post("/commit")
    async def git_commit(message: str = "", auto: bool = False, repo: str = ""):
        git = _git(repo)
        if auto:
            result = await git.auto_commit_async()
        else:
            result = git.commit(message or "auto: commit")
        return {"success": result.success, "message": result.message, "commit_hash": result.commit_hash, "error": result.error}

    @router.post("/push")
    async def git_push(repo: str = ""):
        git = _git(repo)
        stdout, stderr = git._run("push")
        return {"ok": not stderr or "error" not in stderr.lower(), "output": stderr or stdout}

    @router.post("/pull")
    async def git_pull(repo: str = ""):
        git = _git(repo)
        stdout, stderr = git._run("pull")
        return {"ok": not stderr or "error" not in stderr.lower(), "output": stderr or stdout}

    @router.post("/checkout")
    async def git_checkout(branch: str, create: bool = False, repo: str = ""):
        git = _git(repo)
        args = ["checkout"]
        if create:
            args += ["-b"]
        args.append(branch)
        stdout, stderr = git._run(*args)
        return {"ok": not stderr or "error" not in stderr.lower(), "output": stderr or stdout, "branch": branch}

    @router.post("/pr")
    async def git_create_pr(title: str = "", body: str = "", repo: str = ""):
        git = _git(repo)
        result = await git.create_pr_async(title=title, body=body)
        return {"success": result.success, "url": result.url, "error": result.error}

    @router.post("/review")
    async def git_review(file_path: str = "", repo: str = ""):
        git = _git(repo)
        result = await git.llm_review(file_path or None)
        return {
            "summary": result.summary,
            "comments": [
                {"file": c.file, "line": c.line, "severity": c.severity, "message": c.message} for c in result.comments
            ],
        }

    return router
