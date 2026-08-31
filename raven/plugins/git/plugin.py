from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

PLUGIN_NAME = "git"
PLUGIN_DESCRIPTION = "Git operations: status, log, diff, commit, branch, PR"


def _allowed_roots() -> tuple[Path, ...]:
    workspace = os.environ.get("RAVEN_WORKSPACE")
    roots = [Path.cwd().resolve(), Path(tempfile.gettempdir()).resolve()]
    if workspace:
        roots.append(Path(workspace).expanduser().resolve())
    return tuple(roots)


def _check_repo_path(repo_path: str) -> Path:
    p = Path(repo_path).expanduser().resolve()
    for root in _allowed_roots():
        if p == root or root in p.parents:
            return p
    msg = f"Access denied: {repo_path} (git repo outside allowed roots)"
    raise PermissionError(msg)


async def git_status(path: str = ".") -> str:
    """Show git status. Args: path (str): Repository path"""
    return await _run_git(["status"], path)


async def git_log(path: str = ".", count: int = 10) -> str:
    """Show recent commit log. Args: path (str): Repository path, count (int): Number of commits"""
    return await _run_git(["log", "--oneline", f"-{count}"], path)


async def git_diff(path: str = ".", staged: bool = False) -> str:
    """Show uncommitted diff. Args: path (str): Repository path, staged (bool): Show staged diff only"""
    args = ["diff"]
    if staged:
        args.append("--cached")
    return await _run_git(args, path)


async def git_commit(path: str = ".", message: str = "") -> str:
    """Stage all and commit. Args: path (str): Repository path, message (str): Commit message"""
    if not message:
        return "Commit message is required"
    await _run_git(["add", "-A"], path)
    return await _run_git(["commit", "-m", message[:200]], path)


async def git_branch(path: str = ".", create: str = "") -> str:
    """List or create branches. Args: path (str): Repository path, create (str): Branch name to create (empty = list)"""
    if create:
        return await _run_git(["checkout", "-b", create], path)
    return await _run_git(["branch", "-a"], path)


_ALLOWED_REMOTES = frozenset({"origin", "upstream", "main", "master", "production"})

_VALID_REMOTE = "^[A-Za-z0-9._-]+$"


def _validate_remote(remote: str) -> str | None:
    if not remote or "://" in remote or ".." in remote or remote != remote.strip():
        return "Invalid remote"
    if remote not in _ALLOWED_REMOTES:
        return f"Remote '{remote}' not allowed. Use one of: {', '.join(sorted(_ALLOWED_REMOTES))}"
    return None


async def git_push(path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Push to remote. Args: path (str): Repository path, remote (str): Remote name, branch (str): Branch name"""
    err = _validate_remote(remote)
    if err:
        return f"Error: {err}"
    if branch:
        return await _run_git(["push", remote, branch], path)
    return await _run_git(["push", remote], path)


async def git_pull(path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Pull from remote. Args: path (str): Repository path, remote (str): Remote name, branch (str): Branch name"""
    err = _validate_remote(remote)
    if err:
        return f"Error: {err}"
    if branch:
        return await _run_git(["pull", remote, branch], path)
    return await _run_git(["pull", remote], path)


async def _run_git(args: list[str], repo_path: str) -> str:
    try:
        cwd = _check_repo_path(repo_path) if repo_path != "." else None
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        result = ""
        if stdout:
            result += stdout.decode("utf-8", errors="replace")
        if stderr:
            err = stderr.decode("utf-8", errors="replace").strip()
            if err:
                result += f"\n[stderr]\n{err}"
        if proc.returncode is not None and proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"
        return result[:3000] or "(no output)"
    except FileNotFoundError:
        return "Git not found. Install git: https://git-scm.com"
    except PermissionError as e:
        return f"Git error: {e}"
    except Exception as e:
        return f"Git error: {e}"
