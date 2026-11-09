from __future__ import annotations

import asyncio

from loguru import logger

from raven.core.workspace import confine

PLUGIN_NAME = "git"
PLUGIN_DESCRIPTION = "Git operations: status, log, diff, commit, branch, PR"


async def git_status(path: str = ".") -> str:
    """Report changed, staged and untracked files in a repository.

    path: Repository directory, inside the workspace or the temp directory; anywhere else is refused.
    """
    return await _run_git(["status"], path)


async def git_log(path: str = ".", count: int = 10) -> str:
    """List recent commits on one line each, newest first.

    path: Repository directory, inside the allowed roots.
    count: How many commits to show.
    """
    return await _run_git(["log", "--oneline", f"-{count}"], path)


async def git_diff(path: str = ".", staged: bool = False) -> str:
    """Show the patch of work that has not been committed yet, up to 3000 characters.

    path: Repository directory, inside the allowed roots.
    staged: Compare the index against HEAD instead of the working tree against the index.
    """
    args = ["diff"]
    if staged:
        args.append("--cached")
    return await _run_git(args, path)


async def git_commit(path: str = ".", message: str = "") -> str:
    """Run git add -A on the whole repository, then commit with the given message.

    path: Repository directory, inside the allowed roots. Every untracked file the repository can see is staged, so
        check git_status first.
    message: Commit message, cut to 200 characters. Empty is refused before anything is staged.
    """
    if not message:
        return "Commit message is required"
    await _run_git(["add", "-A"], path)
    return await _run_git(["commit", "-m", message[:200]], path)


async def git_branch(path: str = ".", create: str = "") -> str:
    """List every local and remote branch, or create one and switch to it.

    path: Repository directory, inside the allowed roots.
    create: Branch name to create and check out. Empty just lists the branches.
    """
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
    """Publish commits to a remote repository.

    path: Repository directory, inside the allowed roots.
    remote: Remote name, limited to origin, upstream, main, master and production; a URL is refused.
    branch: Branch to push. Empty pushes the current branch as the remote has it configured.
    """
    err = _validate_remote(remote)
    if err:
        return f"Error: {err}"
    if branch:
        return await _run_git(["push", remote, branch], path)
    return await _run_git(["push", remote], path)


async def git_pull(path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Fetch and merge commits from a remote repository into the working tree.

    path: Repository directory, inside the allowed roots.
    remote: Remote name, limited to origin, upstream, main, master and production; a URL is refused.
    branch: Remote branch to merge. Empty uses the branch the current one tracks.
    """
    err = _validate_remote(remote)
    if err:
        return f"Error: {err}"
    if branch:
        return await _run_git(["pull", remote, branch], path)
    return await _run_git(["pull", remote], path)


async def _run_git(args: list[str], repo_path: str) -> str:
    try:
        cwd = confine(repo_path) if repo_path != "." else None
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
        logger.debug("[git] permission error: {}", e)
        return f"Git error: {e}"
    except Exception as e:
        logger.debug("[git] error: {}", e)
        return f"Git error: {e}"
