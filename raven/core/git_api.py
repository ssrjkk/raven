from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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

    @router.get("/log/detail/{commit_hash:str}")
    async def git_log_detail(commit_hash: str, repo: str = ""):
        git = _git(repo)
        stdout, _ = git._run("log", "-1", "--format=%H|%h|%s|%an|%ae|%ad|%ai|%D", "--date=short", commit_hash)
        parts = stdout.split("|")
        if len(parts) < 8:
            return {"error": "commit not found"}
        stat_out, _ = git._run("diff-tree", "--no-commit-id", "-r", "--numstat", commit_hash)
        files: list[dict[str, Any]] = []
        total_added = 0
        total_deleted = 0
        for line in stat_out.split("\n"):
            if line.strip():
                sp = line.split("\t")
                if len(sp) >= 3:
                    added = int(sp[0]) if sp[0] != "-" else 0
                    deleted = int(sp[1]) if sp[1] != "-" else 0
                    total_added += added
                    total_deleted += deleted
                    files.append({"path": sp[2], "added": added, "deleted": deleted})
        diff_out, _ = git._run("diff", commit_hash + "^.." + commit_hash)
        return {
            "hash_full": parts[0],
            "hash": parts[1],
            "message": parts[2],
            "author": parts[3],
            "author_email": parts[4],
            "date": parts[5],
            "date_iso": parts[6],
            "refs": parts[7],
            "files": files,
            "total_added": total_added,
            "total_deleted": total_deleted,
            "total_files": len(files),
            "diff": diff_out,
        }

    @router.get("/diff")
    async def git_diff(staged: bool = False, repo: str = ""):
        return {"diff": _git(repo).get_diff(staged=staged)}

    @router.get("/diff/commit/{commit_hash}")
    async def git_diff_commit(commit_hash: str, repo: str = ""):
        git = _git(repo)
        stdout, _ = git._run("diff", commit_hash + "^.." + commit_hash)
        parsed = _parse_diff(stdout)
        return {"diff": stdout, "files": parsed}

    @router.get("/blame")
    async def git_blame(file: str, repo: str = ""):
        git = _git(repo)
        stdout, stderr = git._run("blame", "--line-porcelain", file)
        if stderr and "fatal" in stderr:
            return {"error": stderr, "lines": []}
        lines: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in stdout.split("\n"):
            if not line:
                continue
            if line.startswith("\t"):
                current["content"] = line[1:]
                if current.get("hash"):
                    lines.append(current)
                current = {}
            elif " " in line:
                key, _, val = line.partition(" ")
                if key == "author":
                    current["author"] = val
                elif key == "author-mail":
                    current["email"] = val.strip("<>")
                elif key == "author-time":
                    current["timestamp"] = val
                elif key == "summary":
                    current["summary"] = val
                elif key == "filename":
                    current["filename"] = val
                elif not current.get("hash"):
                    sp = line.split(" ", 3)
                    if len(sp) >= 1:
                        current["hash"] = sp[0]
                        current["orig_lineno"] = sp[1] if len(sp) > 1 else ""
        return {"lines": lines, "file": file}

    @router.post("/commit")
    async def git_commit(message: str = "", auto: bool = False, repo: str = ""):
        git = _git(repo)
        if auto:
            result = await git.auto_commit_async()
        else:
            result = git.commit(message or "auto: commit")
        return {
            "success": result.success,
            "message": result.message,
            "commit_hash": result.commit_hash,
            "error": result.error,
        }

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


def _parse_diff(diff: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            if current:
                files.append(current)
            current = {"path": line.split(" b/")[-1] if " b/" in line else line, "hunks": [], "added": 0, "deleted": 0}
        elif current is not None and line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            hunk = {"old_start": 0, "new_start": int(m.group(1)) if m else 0, "lines": []}
            current["hunks"].append(hunk)
        elif current is not None and current["hunks"]:
            current["hunks"][-1]["lines"].append(line)
            if line.startswith("+"):
                current["added"] += 1
            elif line.startswith("-"):
                current["deleted"] += 1
    if current:
        files.append(current)
    return files
