from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

PLUGIN_NAME = "files"
PLUGIN_DESCRIPTION = "Read, write, list, and manage files on the local filesystem"

ALLOWED_ROOTS = (str(Path.home()), str(Path.cwd()), tempfile.gettempdir())


def _check_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    allowed = False
    for root in ALLOWED_ROOTS:
        r = Path(root).resolve()
        if r in p.parents or p == r:
            allowed = True
            break
    if not allowed:
        msg = f"Access denied: {path} (allowed: ~, cwd, /tmp)"
        raise PermissionError(msg)
    return p


async def read(path: str, encoding: str = "utf-8", limit: int | None = None) -> str:
    p = _check_path(path)
    content = await asyncio.to_thread(lambda: p.read_text(encoding=encoding))
    if limit and len(content) > limit:
        content = content[:limit] + f"\n... [truncated to {limit} chars]"
    return content


async def write(path: str, content: str, encoding: str = "utf-8") -> str:
    p = _check_path(path)
    await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(lambda: p.write_text(content, encoding=encoding))
    return f"Written {len(content)} bytes to {path}"


async def append(path: str, content: str, encoding: str = "utf-8") -> str:
    p = _check_path(path)

    def _append():
        with p.open("a", encoding=encoding) as f:
            f.write(content)

    await asyncio.to_thread(_append)
    return f"Appended {len(content)} bytes to {path}"


async def ls(path: str = ".", pattern: str = "*") -> str:
    p = _check_path(path)
    is_dir = await asyncio.to_thread(p.is_dir)
    if not is_dir:
        return f"Error: {path} is not a directory"
    items = await asyncio.to_thread(lambda: sorted(p.glob(pattern)))
    if not items:
        return f"No files matching '{pattern}' in {path}"
    lines = []
    for item in items:
        is_file = await asyncio.to_thread(item.is_file)
        size = (await asyncio.to_thread(item.stat)).st_size if is_file else 0
        kind = "📄" if is_file else "📁"
        lines.append(f"{kind} {item.name:30s} {size:>8,d}B")
    total = len(lines)
    return f"{path} ({total} items):\n" + "\n".join(lines)


async def glob(pattern: str, root: str = ".") -> str:
    p = _check_path(root)
    matches = await asyncio.to_thread(lambda: sorted(p.glob(pattern)))
    if not matches:
        return f"No matches for '{pattern}' in {root}"
    lines = [str(m.relative_to(p)) for m in matches[:100]]
    total = len(lines)
    return f"Found {total} file(s):\n" + "\n".join(lines)


async def info(path: str) -> str:
    p = _check_path(path)
    exists = await asyncio.to_thread(p.exists)
    if not exists:
        return f"Path does not exist: {path}"
    stat = await asyncio.to_thread(p.stat)
    is_dir = await asyncio.to_thread(p.is_dir)
    is_file = await asyncio.to_thread(p.is_file)
    kind = "directory" if is_dir else "file" if is_file else "other"
    return (
        f"Path: {p}\n"
        f"Type: {kind}\n"
        f"Size: {stat.st_size:,} bytes\n"
        f"Modified: {stat.st_mtime}\n"
        f"Permissions: {oct(stat.st_mode)[-3:]}"
    )
