from __future__ import annotations

import asyncio

from raven.core.workspace import confine

PLUGIN_NAME = "files"
PLUGIN_DESCRIPTION = "Read, write, list, and manage files on the local filesystem"


async def read(path: str, encoding: str = "utf-8", limit: int | None = None) -> str:
    """Read a text file from the workspace or the temp directory and return its contents.

    path: File to read, inside the workspace or the temp directory; anywhere else raises PermissionError.
    encoding: Text encoding used to decode the file.
    limit: Maximum number of characters to return; the rest is cut and the cut is reported. Unset returns the whole
        file.
    """
    p = confine(path)
    content = await asyncio.to_thread(lambda: p.read_text(encoding=encoding))
    if limit and len(content) > limit:
        content = content[:limit] + f"\n... [truncated to {limit} chars]"
    return content


async def write(path: str, content: str, encoding: str = "utf-8") -> str:
    """Create or replace a text file, making parent directories as needed, and report the bytes written.

    path: File to write, inside the workspace or the temp directory.
    content: Full new contents; anything already at this path is discarded.
    encoding: Text encoding used to write the file.
    """
    p = confine(path)
    await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(lambda: p.write_text(content, encoding=encoding))
    return f"Written {len(content.encode(encoding))} bytes to {path}"


async def append(path: str, content: str, encoding: str = "utf-8") -> str:
    """Add text to the end of a file, creating it when missing, and report the bytes appended.

    path: File to extend, inside the workspace or the temp directory.
    content: Text to append; nothing is written before it, so a trailing newline in an earlier write is not added
        for you.
    encoding: Text encoding of the file.
    """
    p = confine(path)

    def _append():
        with p.open("a", encoding=encoding) as f:
            f.write(content)

    await asyncio.to_thread(_append)
    return f"Appended {len(content.encode(encoding))} bytes to {path}"


async def ls(path: str = ".", pattern: str = "*") -> str:
    """List the entries of a directory with a type marker and size, one per line.

    path: Directory to list, inside the workspace or the temp directory.
    pattern: Glob pattern the entry names are matched against, relative to this directory.
    """
    p = confine(path)
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
    """Find files matching a glob pattern under a directory and return their paths, sorted.

    pattern: Glob pattern, e.g. '**/*.py'. Recursion is up to this pattern, so a leading '**' is needed for
        subdirectories.
    root: Directory to search from, inside the workspace or the temp directory. At most 100 matches are listed.
    """
    p = confine(root)
    matches = await asyncio.to_thread(lambda: sorted(p.glob(pattern)))
    if not matches:
        return f"No matches for '{pattern}' in {root}"
    lines = [str(m.relative_to(p)) for m in matches[:100]]
    total = len(lines)
    shown = f" (showing {total})" if total < len(matches) else ""
    return f"Found {len(matches)} file(s){shown}:\n" + "\n".join(lines)


async def info(path: str) -> str:
    """Report the type, size, modification time and permission bits of one path.

    path: File or directory to describe, inside the workspace or the temp directory. A path that does not exist is
        reported as such rather than raised.
    """
    p = confine(path)
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
