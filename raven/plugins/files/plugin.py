from __future__ import annotations

import glob as glob_mod
import os
from pathlib import Path

from loguru import logger

PLUGIN_NAME = "files"
PLUGIN_DESCRIPTION = "Read, write, list, and manage files on the local filesystem"

ALLOWED_ROOTS = [os.path.expanduser("~"), os.getcwd(), "/tmp"]


def _check_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    allowed = False
    for root in ALLOWED_ROOTS:
        r = Path(root).resolve()
        if r in p.parents or p == r:
            allowed = True
            break
    if not allowed:
        raise PermissionError(f"Access denied: {path} (allowed: ~, cwd, /tmp)")
    return p


async def read(path: str, encoding: str = "utf-8", limit: int | None = None) -> str:
    """Read file contents. Args: path (str): File path, encoding (str): File encoding, limit (int): Max characters to read"""
    p = _check_path(path)
    content = p.read_text(encoding=encoding)
    if limit and len(content) > limit:
        content = content[:limit] + f"\n... [truncated to {limit} chars]"
    return content


async def write(path: str, content: str, encoding: str = "utf-8") -> str:
    """Write content to a file. Creates parent directories if needed. Args: path (str): File path, content (str): Content to write, encoding (str): File encoding"""
    p = _check_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding)
    return f"Written {len(content)} bytes to {path}"


async def append(path: str, content: str, encoding: str = "utf-8") -> str:
    """Append content to a file. Args: path (str): File path, content (str): Content to append, encoding (str): File encoding"""
    p = _check_path(path)
    with p.open("a", encoding=encoding) as f:
        f.write(content)
    return f"Appended {len(content)} bytes to {path}"


async def ls(path: str = ".", pattern: str = "*") -> str:
    """List files in a directory. Args: path (str): Directory path, pattern (str): Glob pattern"""
    p = _check_path(path)
    if not p.is_dir():
        return f"Error: {path} is not a directory"
    items = list(p.glob(pattern))
    if not items:
        return f"No files matching '{pattern}' in {path}"
    lines = []
    for item in sorted(items):
        size = item.stat().st_size if item.is_file() else 0
        kind = "📄" if item.is_file() else "📁"
        lines.append(f"{kind} {item.name:30s} {size:>8,d}B")
    total = len(lines)
    return f"{path} ({total} items):\n" + "\n".join(lines)


async def glob(pattern: str, root: str = ".") -> str:
    """Find files matching a glob pattern. Args: pattern (str): Glob pattern (e.g. '**/*.py'), root (str): Root directory"""
    p = _check_path(root)
    matches = list(p.glob(pattern))
    if not matches:
        return f"No matches for '{pattern}' in {root}"
    lines = [str(m.relative_to(p)) for m in sorted(matches)[:100]]
    total = len(lines)
    return f"Found {total} file(s):\n" + "\n".join(lines)


async def info(path: str) -> str:
    """Get file or directory metadata. Args: path (str): Path to inspect"""
    p = _check_path(path)
    if not p.exists():
        return f"Path does not exist: {path}"
    stat = p.stat()
    kind = "directory" if p.is_dir() else "file" if p.is_file() else "other"
    return (
        f"Path: {p}\n"
        f"Type: {kind}\n"
        f"Size: {stat.st_size:,} bytes\n"
        f"Modified: {stat.st_mtime}\n"
        f"Permissions: {oct(stat.st_mode)[-3:]}"
    )
