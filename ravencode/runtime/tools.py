from __future__ import annotations

import asyncio
import fnmatch
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger


async def read_file(path: str, max_chars: int = 50_000) -> str:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return f"[error] file not found: {path}"
    content = p.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n... (truncated, {len(content)} total chars)"
    return content


async def write_file(path: str, content: str) -> str:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"[ok] wrote {len(content)} chars to {path}"


async def edit_file(path: str, old_string: str, new_string: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return f"[error] file not found: {path}"
    content = p.read_text(encoding="utf-8", errors="replace")
    if old_string not in content:
        return f"[error] old_string not found in {path}"
    count = content.count(old_string)
    if count > 1:
        return f"[error] found {count} occurrences of old_string in {path} — provide more context to make it unique"
    new_content = content.replace(old_string, new_string, 1)
    p.write_text(new_content, encoding="utf-8")
    return f"[ok] applied edit to {path}"


async def glob_files(pattern: str, path: str | None = None) -> list[str]:
    search_root = Path(path).expanduser().resolve() if path else Path.cwd()
    if not search_root.is_dir():
        return [f"[error] directory not found: {path or search_root}"]
    results = []
    for p in search_root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(search_root)
            if fnmatch.fnmatch(str(rel), pattern):
                results.append(str(rel))
    return sorted(results)[:500]


async def grep_files(pattern: str, include: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
    search_root = Path(path).expanduser().resolve() if path else Path.cwd()
    if not search_root.is_dir():
        return [{"error": f"directory not found: {path or search_root}"}]
    results = []
    for p in search_root.rglob("*"):
        if not p.is_file():
            continue
        if include and not fnmatch.fnmatch(p.name, include):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: S112
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern in line or (pattern.startswith("^") and pattern[1:] in line):
                results.append({
                    "file": str(p.relative_to(search_root)),
                    "line": i,
                    "content": line[:200],
                })
                if len(results) >= 200:
                    return results
    return results


async def bash_exec(command: str, timeout: int = 30) -> str:
    allowed_prefixes = (
        "ls", "cat", "head", "tail", "echo", "pwd", "whoami", "date",
        "find", "grep", "rg", "wc", "sort", "uniq", "cut", "tr", "diff",
        "curl", "wget", "ping", "nslookup", "dig",
        "df", "du", "free", "ps", "top", "uptime",
        "git", "make", "npm", "pip", "go", "rustc", "cargo",
        "python", "python3", "node", "mkdir", "cp", "mv", "rm", "chmod",
        "docker", "kubectl", "which", "type", "env",
    )
    cmd_base = command.strip().split()[0] if command.strip() else ""
    if cmd_base not in allowed_prefixes and "/" not in cmd_base:
        return f"[denied] command '{cmd_base}' not in allowlist"
    proc = await asyncio.create_subprocess_exec(
        *command.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        return f"[timeout after {timeout}s]"
    output = ""
    if stdout:
        output += stdout.decode("utf-8", errors="replace")[:30_000]
    if stderr:
        output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")[:10_000]
    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"


async def web_search(query: str, num_results: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        if not results:
            return "(no results)"
        lines = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            lines.append(f"• {title}\n  {body[:200]}\n  {href}")
        return "\n\n".join(lines)
    except ImportError:
        return "[error] duckduckgo_search not installed (pip install duckduckgo_search)"
    except Exception as exc:
        return f"[error] web_search failed: {exc}"


async def web_fetch(url: str) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        text = resp.text[:50_000]
        return text
    except Exception as exc:
        return f"[error] web_fetch failed: {exc}"


async def think(reasoning: str) -> str:
    return f"[thinking: {reasoning}]"


MODULE_TOOLS: dict[str, dict[str, Any]] = {
    "read": {
        "name": "read",
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
        "name": "write",
        "description": "Write content to a file (overwrites existing). Creates parent directories if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
        "handler": write_file,
    },
    "edit": {
        "name": "edit",
        "description": "Edit a file by finding and replacing text. Use precise, unique old_string for single match.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "old_string": {"type": "string", "description": "Text to find (must be unique)"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        "handler": edit_file,
    },
    "glob": {
        "name": "glob",
        "description": "Search for files matching a glob pattern (e.g. '**/*.py'). Returns up to 500 matches.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. 'src/**/*.ts')"},
                "path": {"type": "string", "description": "Root directory (defaults to cwd)", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": glob_files,
    },
    "grep": {
        "name": "grep",
        "description": "Search file contents for a string pattern. Returns up to 200 results with file/line/content.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text to search for"},
                "include": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": None},
                "path": {"type": "string", "description": "Root directory (defaults to cwd)", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": grep_files,
    },
    "bash": {
        "name": "bash",
        "description": "Execute a shell command. Allowed: ls, cat, head, tail, echo, pwd, find, grep, rg, curl, git, make, npm, pip, python, docker, etc.",
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
        "name": "web_search",
        "description": "Search the web for current information. Returns titles, snippets, and URLs.",
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
        "name": "web_fetch",
        "description": "Fetch and return the contents of a URL. Good for reading web pages and APIs.",
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
        "name": "think",
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


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    tool = MODULE_TOOLS.get(name)
    if not tool:
        return f"[error] unknown tool: {name}"
    handler = tool["handler"]
    try:
        result = await handler(**arguments)
        if isinstance(result, list):
            return "\n".join(str(r) for r in result[:200])
        return str(result)
    except Exception as exc:
        logger.exception("Tool {} failed", name)
        return f"[error] {name}: {exc}"
