"""Compact repository map for agent system prompts.

Aider-style: give the model a cheap structural overview (file tree plus
top-level Python class/function signatures) so it can navigate a repository
without burning tool calls on exploratory reads. Pure stdlib (ast), no
network, deterministic output.
"""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path

from loguru import logger

from ravencode.runtime.workspace import get_workspace_root

_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".tox",
    ".idea",
    ".vscode",
    "allure-results",
    "allure-report",
    ".verdent",
    ".next",
    "coverage",
}

_CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".sh",
    ".sql",
}

DEFAULT_MAX_CHARS = 6000
_MAX_FILES = 400
_MAX_SYMBOL_FILES = 120
_GIT_HISTORY_COMMITS = 200
_FOCUS_PARTNERS = 2  # co-change partners injected into the pre-read per task


def _git_commit_files(root: str | Path) -> list[list[str]]:
    """File lists of recent commits, newest first; [] when git unavailable."""
    try:
        proc = subprocess.run(
            ["git", "log", f"-{_GIT_HISTORY_COMMITS}", "--name-only", "--format=%x01"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0 or not proc.stdout:
        return []
    commits: list[list[str]] = []
    current: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line == "\x01":
            if current:
                commits.append(current)
            current = []
        elif line:
            current.append(line.replace("\\", "/"))
    if current:
        commits.append(current)
    return commits


def co_change_scores(root: str | Path) -> dict[str, int]:
    """How often each file changed together with others in recent history.

    Files edited in the same commit tend to belong to the same work surface.
    Returns {} for non-git workspaces or when git is unavailable.
    """
    counts: dict[str, int] = {}
    for files in _git_commit_files(root):
        for f in files:
            counts[f] = counts.get(f, 0) + len(files) - 1
    return counts


def focus_files(root: str | Path, mentioned: list[str], limit: int = _FOCUS_PARTNERS) -> list[str]:
    """Exact co-change partners of the files a task mentions, related-first.

    When a task names ``src/app.py``, the files that historically change
    together with it are likely relevant too — even if the task does not name
    them. Partners already mentioned are excluded.
    """
    if not mentioned:
        return []
    commits = _git_commit_files(root)
    if not commits:
        return []
    mentioned_set = {m.replace("\\", "/") for m in mentioned}
    pair_counts: dict[str, int] = {}
    for files in commits:
        overlap = [f for f in files if f in mentioned_set]
        if not overlap:
            continue
        for f in files:
            if f in mentioned_set:
                continue
            pair_counts[f] = pair_counts.get(f, 0) + len(overlap)
    ranked = sorted(pair_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f for f, _ in ranked[:limit] if f.endswith(tuple(_CODE_SUFFIXES))]


def _python_symbols(path: Path) -> list[str]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, ValueError, OSError):
        return []
    lines: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            args = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
            shown = ", ".join(args[:6]) + (", ..." if len(args) > 6 else "")
            lines.append(f"    {prefix} {node.name}({shown})")
        elif isinstance(node, ast.ClassDef):
            lines.append(f"    class {node.name}")
    return lines


def _parent_is_symlink(base: Path, parts: tuple[str, ...]) -> bool:
    """Check if any parent directory in the path is a symlink."""
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def build_repo_map(
    root: str | Path | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Build a compact map of the repository under ``root``.

    Returns "" when no workspace is available or nothing indexable is found.
    """
    base: Path | None = Path(root) if root is not None else None
    if base is None:
        ws = get_workspace_root()
        base = Path(ws) if ws else None
    if base is None or not base.is_dir():
        return ""

    try:
        all_files: list[Path] = []
        for path in base.rglob("*"):
            if len(all_files) >= _MAX_FILES:
                break
            rel = path.relative_to(base)
            if any(part in _EXCLUDED_DIRS for part in rel.parts[:-1]):
                continue
            if path.is_symlink():
                continue
            if _parent_is_symlink(base, rel.parts[:-1]):
                continue
            if path.is_file() and path.suffix.lower() in _CODE_SUFFIXES:
                all_files.append(path)
    except OSError as exc:
        logger.debug("repo_map: scan failed: {}", exc)
        return ""

    if not all_files:
        return ""

    # Prefer recently modified files: they are the most likely work surface.
    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    all_files.sort(key=_mtime, reverse=True)

    lines = ["Repository map (most recently modified first):"]
    budget = max_chars - len("\n".join(lines)) - 40
    symbols_budget_files = all_files[:_MAX_SYMBOL_FILES]
    symbol_map: dict[Path, list[str]] = {}
    for path in symbols_budget_files:
        if path.suffix.lower() == ".py":
            symbol_map[path] = _python_symbols(path)

    for path in all_files:
        rel_posix = path.relative_to(base).as_posix()
        entry = f"- {rel_posix}"
        syms = symbol_map.get(path)
        if syms:
            entry += "\n" + "\n".join(syms)
        if len(entry) > budget:
            lines.append("  ... (map truncated to fit context budget)")
            break
        lines.append(entry)
        budget -= len(entry) + 1

    result = "\n".join(lines).strip()
    if len(result) > max_chars:
        result = result[:max_chars] + "\n  ... (truncated)"
    logger.debug("repo_map: {} files, {} chars, {:.2f}s", len(all_files), len(result), 0.0)
    return result


def repo_map_block(root: str | Path | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Repo map wrapped as a system-prompt block; "" when nothing to show."""
    started = time.monotonic()
    repo_map = build_repo_map(root, max_chars)
    if not repo_map:
        return ""
    elapsed = time.monotonic() - started
    logger.debug("repo_map built in {:.1f} ms", elapsed * 1000)
    return (
        "\n\n# Repository structure\n"
        "Use this map to locate files before reading them; do not re-list directories:\n"
        + repo_map
    )
