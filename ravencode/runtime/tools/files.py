from __future__ import annotations

import asyncio
import fnmatch
import json
from pathlib import Path
from typing import Any

from loguru import logger

from ravencode.runtime.undo import get_undo_manager
from ravencode.runtime.workspace import (
    _get_workspace,
)
from ravencode.runtime.workspace import (
    confine as _confine,
)

from ._common import (
    _compute_diff,
    _safe_read,
    _safe_write,
)

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




def _fuzzy_find(old_string: str, content: str) -> tuple[int, int] | None:
    """Locate old_string in content ignoring per-line trailing whitespace.

    LLM edits fail constantly on invisible whitespace differences; each
    failure costs a full round-trip. Returns the exact (start, end) span of
    the matching region in the original content, or None when zero or
    multiple regions match.
    """
    def normalize(text: str) -> list[str]:
        return [ln.rstrip() for ln in text.splitlines()]

    target = normalize(old_string)
    if not target:
        return None
    lines = content.splitlines(keepends=True)
    bare = [ln.rstrip("\r\n") for ln in lines]
    stripped = [ln.rstrip() for ln in bare]
    n = len(target)
    hits: list[int] = []
    for i in range(len(stripped) - n + 1):
        if stripped[i : i + n] == target:
            hits.append(i)
    if len(hits) != 1:
        return None
    start = sum(len(ln) for ln in lines[: hits[0]])
    end = sum(len(ln) for ln in lines[: hits[0] + n])
    return start, end




async def edit_file(path: str, old_string: str, new_string: str, preview: bool = False) -> str:
    content, err = await _safe_read(path)
    if err:
        return err
    span: tuple[int, int] | None = None
    if old_string not in content:
        span = _fuzzy_find(old_string, content)
        if span is None:
            return f"[error] old_string not found in {path}"
    count = content.count(old_string)
    if count > 1:
        return f"[error] found {count} occurrences — provide more context"
    if span is not None:
        # The matched region includes the last line's terminator; if the
        # replacement doesn't end with one, keep the original terminator so
        # the following line does not get glued to the edit.
        terminator = ""
        last_line = content[span[0] : span[1]].splitlines(keepends=True)[-1] if span[1] > span[0] else ""
        if last_line.endswith(("\n", "\r")) and not new_string.endswith(("\n", "\r")):
            terminator = last_line[len(last_line.rstrip("\r\n")) :]
        new_content = content[: span[0]] + new_string + terminator + content[span[1] :]
    else:
        new_content = content.replace(old_string, new_string, 1)
    if preview:
        return f"[diff for {path}]\n{_compute_diff(content, new_content, path)}"
    get_undo_manager().record(str(_confine(path)), content, new_content, "edit")
    try:
        await _safe_write(path, new_content)
        note = " (whitespace-tolerant match)" if span is not None else ""
        return f"[ok] applied edit to {path}{note}"
    except PermissionError as exc:
        return f"[error] {exc}"




async def verify_file(path: str) -> str:
    """Syntax/type-check a source file after editing.

    Supports Python (ast.parse + optional ruff/mypy when the tools are
    installed), TypeScript/JavaScript (node --check if available), and JSON
    (json.loads). Returns a summary of any problems found.
    """
    full = _confine(path)
    if not full.is_file():
        return f"[error] file not found: {path}"
    try:
        content = full.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return f"[error] cannot read {path}: {exc}"

    suffix = full.suffix.lower()
    problems: list[str] = []

    def _parse_output(out: bytes, err: bytes) -> str:
        return (out + b"\n" + err).decode("utf-8", "replace").strip()

    if suffix == ".py":
        import ast

        try:
            ast.parse(content)
        except SyntaxError as exc:
            problems.append(f"syntax error (line {exc.lineno}): {exc.msg}")
        if not problems:
            for tool, args in (("ruff", ["check", str(full)]), ("mypy", [str(full)])):
                try:
                    proc = await asyncio.create_subprocess_exec(
                        tool,
                        *args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                except FileNotFoundError:
                    continue
                try:
                    out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
                except TimeoutError:
                    proc.kill()
                    continue
                text = _parse_output(out, err)
                if text and "Success: no issues" not in text and "All checks passed" not in text:
                    problems.append(f"{tool}: {text[:800]}")
    elif suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "node", "--check", str(full),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            pass
        else:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                problems.append(_parse_output(out, err))
    elif suffix == ".json":
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            problems.append((f"invalid JSON (line {exc.lineno}, col {exc.colno}): {exc.msg}")[:500])

    if not problems:
        return f"[ok] {path} is valid"
    return "[problems]\n" + "\n".join(problems)




async def glob_files(pattern: str, path: str | None = None) -> list[str]:
    search_root = _get_workspace() if path is None else _confine(path)
    if not search_root.is_dir():
        return [f"[error] directory not found: {path or search_root}"]
    return await asyncio.to_thread(_glob_scan, search_root, pattern)




def _glob_scan(search_root: Path, pattern: str) -> list[str]:
    results = []
    for p in search_root.rglob("*"):
        if p.is_file() and fnmatch.fnmatch(str(p.relative_to(search_root)), pattern):
            results.append(str(p.relative_to(search_root)))
    return sorted(results)[:500]




async def grep_files(
    pattern: str, include: str | None = None, path: str | None = None, use_regex: bool = False
) -> list[dict[str, Any]]:
    import re

    search_root = _get_workspace() if path is None else _confine(path)
    if not search_root.is_dir():
        return [{"error": f"directory not found: {path or search_root}"}]
    try:
        matcher = re.compile(pattern) if use_regex else None
    except re.error as exc:
        return [{"error": f"invalid regex: {exc}"}]
    results = []
    for p in search_root.rglob("*"):
        if not p.is_file():
            continue
        if include and not fnmatch.fnmatch(p.name, include):
            continue
        try:
            text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError, PermissionError) as e:
            logger.debug("Skipping unreadable file {}: {}", p, e)
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if (matcher is not None and matcher.search(line)) or (matcher is None and pattern in line):
                results.append({"file": str(p.relative_to(search_root)), "line": i, "content": line[:200]})
                if len(results) >= 200:
                    return results
    return results
