from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from loguru import logger

PLUGIN_NAME = "git"
PLUGIN_DESCRIPTION = "Git operations: status, log, diff, commit, branch, PR"


async def git_status(path: str = ".") -> str:
    """Show git status. Args: path (str): Repository path"""
    return await _run_git("status", path)


async def git_log(path: str = ".", count: int = 10) -> str:
    """Show recent commit log. Args: path (str): Repository path, count (int): Number of commits"""
    return await _run_git(f"log --oneline -{count}", path)


async def git_diff(path: str = ".", staged: bool = False) -> str:
    """Show uncommitted diff. Args: path (str): Repository path, staged (bool): Show staged diff only"""
    flag = "--cached" if staged else ""
    return await _run_git(f"diff {flag}", path)


async def git_commit(path: str = ".", message: str = "") -> str:
    """Stage all and commit. Args: path (str): Repository path, message (str): Commit message"""
    if not message:
        return "Commit message is required"
    safe_msg = message.replace('"', '\\"')[:200]
    await _run_git("add -A", path)
    return await _run_git(f'commit -m "{safe_msg}"', path)


async def git_branch(path: str = ".", create: str = "") -> str:
    """List or create branches. Args: path (str): Repository path, create (str): Branch name to create (empty = list)"""
    if create:
        return await _run_git(f"checkout -b {create}", path)
    return await _run_git("branch -a", path)


async def git_push(path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Push to remote. Args: path (str): Repository path, remote (str): Remote name, branch (str): Branch name"""
    ref = f"{remote} {branch}" if branch else remote
    return await _run_git(f"push {ref}", path)


async def git_pull(path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Pull from remote. Args: path (str): Repository path, remote (str): Remote name, branch (str): Branch name"""
    ref = f"{remote} {branch}" if branch else remote
    return await _run_git(f"pull {ref}", path)


async def _run_git(args: str, repo_path: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *shlex.split(args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=Path(repo_path).resolve() if repo_path != "." else None,
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
    except Exception as e:
        return f"Git error: {e}"
