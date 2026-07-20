from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_MAX_LIST_ITEMS = 1000

if sys.platform == "win32":
    _O_NOFOLLOW = 0
else:
    _O_NOFOLLOW = os.O_NOFOLLOW


def _workspace() -> Path:
    return Path(os.environ.get("RAVEN_WORKSPACE", "data")).resolve()


def _check_no_symlinks_in_path(p: Path, ws: Path) -> None:
    current = ws
    for part in p.relative_to(ws).parts:
        current = current / part
        if current.is_symlink():
            raise PermissionError(f"Symlink detected in path: {current}")


def _confine(path: str) -> Path:
    p = Path(os.path.normpath(Path(path).expanduser()))
    ws = _workspace()
    try:
        p.relative_to(ws)
    except ValueError:
        raise PermissionError(f"Access denied: path outside workspace: {p}") from None
    _check_no_symlinks_in_path(p, ws)
    return p


def _confine_fd(path: str, flags: int) -> int:
    p = Path(os.path.normpath(Path(path).expanduser()))
    ws = _workspace()
    try:
        p.relative_to(ws)
    except ValueError:
        raise PermissionError(f"Access denied: path outside workspace: {p}") from None
    _check_no_symlinks_in_path(p, ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(p), flags | _O_NOFOLLOW, 0o644)
    except OSError as e:
        if e.errno == 34:
            raise PermissionError(f"Symlink detected: {p}") from e
        raise
    return fd


async def file_read(path: str, max_size: int = 50000) -> str:
    fd = _confine_fd(path, os.O_RDONLY)
    try:
        size = await asyncio.to_thread(os.lseek, fd, 0, os.SEEK_END)
        await asyncio.to_thread(os.lseek, fd, 0, os.SEEK_SET)
        to_read = min(size, max_size)
        raw = await asyncio.to_thread(os.read, fd, to_read)
        content = raw.decode("utf-8", errors="replace")
        if size > max_size:
            content += f"\n... (truncated, {size} total bytes)"
        return content
    finally:
        await asyncio.to_thread(os.close, fd)


async def file_write(path: str, content: str) -> str:
    fd = _confine_fd(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW)
    try:
        await asyncio.to_thread(os.write, fd, content.encode("utf-8"))
    finally:
        await asyncio.to_thread(os.close, fd)
    return f"Written {len(content)} bytes to {path}"


async def file_append(path: str, content: str) -> str:
    fd = _confine_fd(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | _O_NOFOLLOW)
    try:
        await asyncio.to_thread(os.write, fd, content.encode("utf-8"))
    finally:
        await asyncio.to_thread(os.close, fd)
    return f"Appended {len(content)} bytes to {path}"


async def file_list(path: str = ".", pattern: str = "*") -> str:
    p = _confine(path)
    exists = await asyncio.to_thread(p.exists)
    if not exists:
        raise FileNotFoundError(f"Directory not found: {p}")
    items: list[str] = []
    depth = 0
    for f in await asyncio.to_thread(lambda: list(p.glob(pattern))):
        if len(items) >= _MAX_LIST_ITEMS:
            items.append("... (truncated, too many files)")
            break
        kind = "📁" if await asyncio.to_thread(f.is_dir) else "📄"
        size = (await asyncio.to_thread(f.stat)).st_size if await asyncio.to_thread(f.is_file) else 0
        items.append(f"{kind} {f.name}  ({size} bytes)" if size else f"{kind} {f.name}")
        try:
            rel = f.relative_to(p)
            depth = len(rel.parts)
        except ValueError:
            pass
        if depth > 10:
            items.append("... (truncated, depth limit reached)")
            break
    return "\n".join(items[:200]) if items else "(empty)"


async def file_delete(path: str) -> str:
    p = _confine(path)
    is_file = await asyncio.to_thread(p.is_file)
    if is_file:
        await asyncio.to_thread(p.unlink)
        return f"Deleted {p}"
    is_dir = await asyncio.to_thread(p.is_dir)
    if is_dir:
        import shutil

        await asyncio.to_thread(shutil.rmtree, p)
        return f"Deleted directory {p}"
    raise FileNotFoundError(f"Not found: {p}")


def register_file_tools(registry: ToolRegistry) -> None:
    registry.register(
            ToolSpec(
                name="file_read",
                description="Read the contents of a file (max 50KB by default)",
                parameters={
                    "path": {"type": "string", "description": "Path to the file", "required": True},
                    "max_size": {"type": "integer", "description": "Max bytes to read", "required": False},
                },
            handler=file_read,
            category="file",
        )
    )
    registry.register(
        ToolSpec(
            name="file_write",
            description="Write content to a file (overwrites existing)",
            parameters={
                "path": {"type": "string", "description": "Path to the file", "required": True},
                "content": {"type": "string", "description": "Content to write", "required": True},
            },
            handler=file_write,
            category="file",
        )
    )
    registry.register(
        ToolSpec(
            name="file_append",
            description="Append content to a file",
            parameters={
                "path": {"type": "string", "description": "Path to the file", "required": True},
                "content": {"type": "string", "description": "Content to append", "required": True},
            },
            handler=file_append,
            category="file",
        )
    )
    registry.register(
        ToolSpec(
            name="file_list",
            description="List files in a directory matching a glob pattern",
            parameters={
                "path": {"type": "string", "description": "Directory path", "required": False},
                "pattern": {"type": "string", "description": "Glob pattern (e.g. *.py)", "required": False},
            },
            handler=file_list,
            category="file",
        )
    )
    registry.register(
        ToolSpec(
            name="file_delete",
            description="Delete a file or directory",
            parameters={
                "path": {"type": "string", "description": "Path to delete", "required": True},
            },
            handler=file_delete,
            category="file",
        )
    )
