from __future__ import annotations

import os
from pathlib import Path

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def file_read(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    return p.read_text(encoding="utf-8", errors="replace")[:50000]


async def file_write(path: str, content: str) -> str:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {p}"


async def file_append(path: str, content: str) -> str:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(content)
    return f"Appended {len(content)} bytes to {p}"


async def file_list(path: str = ".", pattern: str = "*") -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {p}")
    items = []
    for f in p.glob(pattern):
        kind = "📁" if f.is_dir() else "📄"
        size = f.stat().st_size if f.is_file() else 0
        items.append(f"{kind} {f.name}  ({size} bytes)" if size else f"{kind} {f.name}")
    return "\n".join(items[:200]) if items else "(empty)"


async def file_delete(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if p.is_file():
        p.unlink()
        return f"Deleted {p}"
    elif p.is_dir():
        import shutil
        shutil.rmtree(p)
        return f"Deleted directory {p}"
    raise FileNotFoundError(f"Not found: {p}")


def register_file_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="file_read",
        description="Read the contents of a file",
        parameters={
            "path": {"type": "string", "description": "Path to the file", "required": True},
        },
        handler=file_read,
        category="file",
    ))
    registry.register(ToolSpec(
        name="file_write",
        description="Write content to a file (overwrites existing)",
        parameters={
            "path": {"type": "string", "description": "Path to the file", "required": True},
            "content": {"type": "string", "description": "Content to write", "required": True},
        },
        handler=file_write,
        category="file",
    ))
    registry.register(ToolSpec(
        name="file_append",
        description="Append content to a file",
        parameters={
            "path": {"type": "string", "description": "Path to the file", "required": True},
            "content": {"type": "string", "description": "Content to append", "required": True},
        },
        handler=file_append,
        category="file",
    ))
    registry.register(ToolSpec(
        name="file_list",
        description="List files in a directory matching a glob pattern",
        parameters={
            "path": {"type": "string", "description": "Directory path", "required": False},
            "pattern": {"type": "string", "description": "Glob pattern (e.g. *.py)", "required": False},
        },
        handler=file_list,
        category="file",
    ))
    registry.register(ToolSpec(
        name="file_delete",
        description="Delete a file or directory",
        parameters={
            "path": {"type": "string", "description": "Path to delete", "required": True},
        },
        handler=file_delete,
        category="file",
    ))
