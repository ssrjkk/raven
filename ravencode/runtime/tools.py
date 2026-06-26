from __future__ import annotations

import asyncio
import difflib
import fnmatch
import shlex
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.security.ssrf import validate_url

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_WORKSPACE_ROOT: Path | None = None


def _get_workspace() -> Path:
    global _WORKSPACE_ROOT
    if _WORKSPACE_ROOT is None:
        import os
        _WORKSPACE_ROOT = Path(os.environ.get("RAVEN_WORKSPACE", "workspace")).expanduser().resolve()
    return _WORKSPACE_ROOT


def _confine(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    ws = _get_workspace()
    try:
        p.relative_to(ws)
    except ValueError as exc:
        raise PermissionError(f"Path {path} is outside workspace {ws}") from exc
    return p


def _compute_diff(original: str, modified: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=path, tofile=path,
        )
    )


async def _safe_read(path: str, max_chars: int = 50_000) -> tuple[str, str]:
    p = _confine(path)
    if not p.is_file():
        return "", f"[error] file not found: {path}"
    try:
        content = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
    except Exception as exc:
        return "", f"[error] cannot read {path}: {exc}"
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n... (truncated, {len(content)} total chars)"
    return content, ""


async def _safe_write(path: str, content: str) -> None:
    p = _confine(path)
    await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(p.write_text, content, encoding="utf-8")


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------

async def read_file(path: str, max_chars: int = 50_000) -> str:
    content, err = await _safe_read(path, max_chars)
    return err or content


async def write_file(path: str, content: str) -> str:
    try:
        await _safe_write(path, content)
        return f"[ok] wrote {len(content)} chars to {path}"
    except PermissionError as exc:
        return f"[error] {exc}"


async def edit_file(path: str, old_string: str, new_string: str, preview: bool = False) -> str:
    content, err = await _safe_read(path)
    if err:
        return err
    if old_string not in content:
        return f"[error] old_string not found in {path}"
    count = content.count(old_string)
    if count > 1:
        return f"[error] found {count} occurrences — provide more context"
    new_content = content.replace(old_string, new_string, 1)
    if preview:
        return f"[diff for {path}]\n{_compute_diff(content, new_content, path)}"
    try:
        await _safe_write(path, new_content)
        return f"[ok] applied edit to {path}"
    except PermissionError as exc:
        return f"[error] {exc}"


async def glob_files(pattern: str, path: str | None = None) -> list[str]:
    search_root = _get_workspace() if path is None else _confine(path)
    if not search_root.is_dir():
        return [f"[error] directory not found: {path or search_root}"]
    results = []
    for p in search_root.rglob("*"):
        if p.is_file() and fnmatch.fnmatch(str(p.relative_to(search_root)), pattern):
            results.append(str(p.relative_to(search_root)))
    return sorted(results)[:500]


async def grep_files(pattern: str, include: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
    search_root = _get_workspace() if path is None else _confine(path)
    if not search_root.is_dir():
        return [{"error": f"directory not found: {path or search_root}"}]
    results = []
    for p in search_root.rglob("*"):
        if not p.is_file():
            continue
        if include and not fnmatch.fnmatch(p.name, include):
            continue
        try:
            text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
        except Exception:
            logger.debug("Skipping unreadable file: {}", p)
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern in line:
                results.append({"file": str(p.relative_to(search_root)), "line": i, "content": line[:200]})
                if len(results) >= 200:
                    return results
    return results


_BASH_ALLOWLIST = frozenset({
    "ls", "cat", "head", "tail", "echo", "pwd", "whoami", "date",
    "find", "grep", "rg", "wc", "sort", "uniq", "cut", "tr", "diff",
    "curl", "wget", "df", "du", "free", "ps", "top", "uptime",
    "git", "make", "npm", "pip", "go", "rustc", "cargo",
    "python", "python3", "node", "mkdir", "cp", "mv", "rm", "chmod", "touch",
    "docker", "kubectl", "which", "type", "env", "npx", "pwsh", "powershell",
})


async def bash_exec(command: str, timeout: int = 30) -> str:
    parts = shlex.split(command)
    if not parts:
        return "[error] empty command"
    cmd_base = Path(parts[0]).name
    if cmd_base not in _BASH_ALLOWLIST:
        return f"[denied] command '{cmd_base}' not in allowlist"
    proc = await asyncio.create_subprocess_exec(
        *parts,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return f"[timeout after {timeout}s]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:30_000]
    if stderr:
        output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:10_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"


async def web_search(query: str, num_results: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        if not results:
            return "(no results)"
        return "\n\n".join(
            f"• {r.get('title', '')}\n  {r.get('body', '')[:200]}\n  {r.get('href', '')}"
            for r in results
        )
    except ImportError:
        return "[error] duckduckgo_search not installed"
    except Exception as exc:
        logger.exception("web_search failed")
        return f"[error] web_search: {exc}"


async def web_fetch(url: str) -> str:
    if not validate_url(url):
        return f"[denied] URL blocked by SSRF guard: {url}"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Raven/1.0"})
            resp.raise_for_status()
        return resp.text[:50_000]
    except Exception as exc:
        logger.exception("web_fetch failed")
        return f"[error] web_fetch: {exc}"


async def think(reasoning: str) -> str:
    return f"[thinking: {reasoning}]"


_TASK_DEPTH = 0
_MAX_TASK_DEPTH = 5


async def task_delegate(description: str, context: str | None = None) -> str:
    global _TASK_DEPTH
    if _TASK_DEPTH >= _MAX_TASK_DEPTH:
        return f"[error] max task delegation depth ({_MAX_TASK_DEPTH}) exceeded"
    _TASK_DEPTH += 1
    try:
        from ravencode.runtime.agent_core import ReActAgent
        sub = ReActAgent(max_steps=15)
        prompt = f"{context}\n\n{description}" if context else description
        return await sub.run(prompt)
    finally:
        _TASK_DEPTH -= 1


# ---------------------------------------------------------------------------
# git tools
# ---------------------------------------------------------------------------

async def _git_cmd(*args: str, cwd: str | None = None) -> str:
    cmd = ["git"] + list(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd or str(Path.cwd()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except TimeoutError:
        return "[timeout]"
    output = (stdout or b"").decode("utf-8", errors="replace")[:20_000]
    if stderr:
        output += "\n" + stderr.decode("utf-8", errors="replace")[:5_000]
    if proc.returncode:
        output += f"\n[exit code: {proc.returncode}]"
    return output


async def git_status(path: str | None = None) -> str:
    return await _git_cmd("status", cwd=path)


async def git_diff(path: str | None = None, staged: bool = False) -> str:
    args = ["diff", "--cached"] if staged else ["diff"]
    return await _git_cmd(*args, cwd=path)


async def git_log(max_count: int = 10, path: str | None = None) -> str:
    return await _git_cmd("log", f"--max-count={max_count}", "--oneline", cwd=path)


async def git_commit(message: str, path: str | None = None) -> str:
    return await _git_cmd("commit", "-m", message, cwd=path)


async def git_add(files: str, path: str | None = None) -> str:
    return await _git_cmd("add", *files.split(), cwd=path)


# ---------------------------------------------------------------------------
# image / multimodal
# ---------------------------------------------------------------------------

async def read_image(path: str) -> str:
    try:
        p = _confine(path)
    except PermissionError as exc:
        return f"[error] {exc}"
    if not p.is_file():
        return f"[error] file not found: {path}"
    ext = p.suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"):
        return f"[error] unsupported image format: {ext}"
    import base64
    data = base64.b64encode(p.read_bytes()[:500_000]).decode("ascii")
    return f"Image ({p.stat().st_size} bytes, {ext}): data:image/{ext[1:]};base64,{data}"


# ---------------------------------------------------------------------------
# tool registry
# ---------------------------------------------------------------------------

MODULE_TOOLS: dict[str, dict[str, Any]] = {
    "read": {
        "name": "read", "dangerous": False,
        "description": "Read the contents of a file. Returns up to 50,000 characters.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "max_chars": {"type": "integer", "description": "Max chars to return (default 50000)", "default": 50000},
            },
            "required": ["path"],
        },
        "handler": read_file,
    },
    "write": {
        "name": "write", "dangerous": True,
        "description": "Write content to a file (overwrites existing). Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
        "handler": write_file,
    },
    "edit": {
        "name": "edit", "dangerous": True,
        "description": "Edit a file by finding and replacing text. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
                "old_string": {"type": "string", "description": "Text to find (must be unique)"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "preview": {"type": "boolean", "description": "Show diff without applying", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
        "handler": edit_file,
    },
    "glob": {
        "name": "glob", "dangerous": False,
        "description": "Search for files matching a glob pattern. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. 'src/**/*.ts')"},
                "path": {"type": "string", "description": "Subdirectory inside workspace", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": glob_files,
    },
    "grep": {
        "name": "grep", "dangerous": False,
        "description": "Search file contents for a string pattern. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text to search for"},
                "include": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": None},
                "path": {"type": "string", "description": "Subdirectory inside workspace", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": grep_files,
    },
    "bash": {
        "name": "bash", "dangerous": True,
        "description": "Execute a shell command from the allowlist. Supports quoted arguments.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
            },
            "required": ["command"],
        },
        "handler": bash_exec,
    },
    "web_search": {
        "name": "web_search", "dangerous": False,
        "description": "Search the web for current information (DuckDuckGo).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        "handler": web_search,
    },
    "web_fetch": {
        "name": "web_fetch", "dangerous": False,
        "description": "Fetch URL contents. SSRF-guarded against private IP ranges.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
        "handler": web_fetch,
    },
    "think": {
        "name": "think", "dangerous": False,
        "description": "Use this tool to reason about the problem before taking action. No external effect.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string", "description": "Your step-by-step reasoning"},
            },
            "required": ["reasoning"],
        },
        "handler": think,
    },
    "task": {
        "name": "task", "dangerous": False,
        "description": "Delegate a sub-task to a new agent (max depth 5). Use for parallel work.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Task description for the sub-agent"},
                "context": {"type": "string", "description": "Optional context to pass", "default": None},
            },
            "required": ["description"],
        },
        "handler": task_delegate,
    },
    "git_status": {
        "name": "git_status", "dangerous": False,
        "description": "Show git working tree status.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": [],
        },
        "handler": git_status,
    },
    "git_diff": {
        "name": "git_diff", "dangerous": False,
        "description": "Show git diff of unstaged changes, or staged changes with staged=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
                "staged": {"type": "boolean", "description": "Show staged diff instead", "default": False},
            },
            "required": [],
        },
        "handler": git_diff,
    },
    "git_log": {
        "name": "git_log", "dangerous": False,
        "description": "Show recent git commit history (one-line format).",
        "parameters": {
            "type": "object",
            "properties": {
                "max_count": {"type": "integer", "description": "Number of commits (default 10)", "default": 10},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": [],
        },
        "handler": git_log,
    },
    "git_commit": {
        "name": "git_commit", "dangerous": True,
        "description": "Create a git commit with the given message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": ["message"],
        },
        "handler": git_commit,
    },
    "git_add": {
        "name": "git_add", "dangerous": True,
        "description": "Stage files for commit.",
        "parameters": {
            "type": "object",
            "properties": {
                "files": {"type": "string", "description": "Files to stage (space-separated)"},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": ["files"],
        },
        "handler": git_add,
    },
    "read_image": {
        "name": "read_image", "dangerous": False,
        "description": "Read an image file (png, jpg, gif, webp, svg) confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
            },
            "required": ["path"],
        },
        "handler": read_image,
    },
}


def get_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in MODULE_TOOLS.values()
    ]


def is_dangerous(name: str) -> bool:
    t = MODULE_TOOLS.get(name)
    return t.get("dangerous", False) if t else False


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    tool = MODULE_TOOLS.get(name)
    if not tool:
        return f"[error] unknown tool: {name}"
    try:
        result = await tool["handler"](**arguments)
        if isinstance(result, list):
            return "\n".join(str(r) for r in result[:200])
        return str(result)
    except Exception as exc:
        logger.exception("Tool {} failed", name)
        return f"[error] {name}: {exc}"
