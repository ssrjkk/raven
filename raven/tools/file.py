from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from raven.core.security.path_guard import confine_path
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
            msg = f"Symlink detected in path: {current}"
            raise PermissionError(msg)


def _confine(path: str) -> Path:
    p = confine_path(path, _workspace())
    _check_no_symlinks_in_path(p, _workspace())
    return p


def _confine_fd(path: str, flags: int) -> int:
    p = confine_path(path, _workspace())
    _check_no_symlinks_in_path(p, _workspace())
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(p), flags | _O_NOFOLLOW, 0o644)
    except OSError as e:
        if e.errno == 34:
            msg = f"Symlink detected: {p}"
            raise PermissionError(msg) from e
        raise
    return fd


_MAX_READ_BYTES = 10 * 1024 * 1024


async def _read_file(path: str, max_size: int = _MAX_READ_BYTES) -> str:
    fd = await asyncio.to_thread(_confine_fd, path, os.O_RDONLY)
    try:
        size = await asyncio.to_thread(os.lseek, fd, 0, os.SEEK_END)
        await asyncio.to_thread(os.lseek, fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = min(size, max_size)
        while remaining > 0:
            chunk = await asyncio.to_thread(os.read, fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        await asyncio.to_thread(os.close, fd)


async def _write_file(path: str, content: str, flags: int = os.O_WRONLY | os.O_CREAT | os.O_TRUNC) -> None:
    fd = await asyncio.to_thread(_confine_fd, path, flags | _O_NOFOLLOW)
    try:
        await asyncio.to_thread(os.write, fd, content.encode("utf-8"))
    finally:
        await asyncio.to_thread(os.close, fd)


async def file_read(path: str, max_size: int = 50000) -> str:
    fd = await asyncio.to_thread(_confine_fd, path, os.O_RDONLY)
    try:
        size = await asyncio.to_thread(os.lseek, fd, 0, os.SEEK_END)
        await asyncio.to_thread(os.lseek, fd, 0, os.SEEK_SET)
        to_read = min(size, max_size)
        chunks: list[bytes] = []
        remaining = to_read
        while remaining > 0:
            chunk = await asyncio.to_thread(os.read, fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks).decode("utf-8", errors="replace")
        if size > max_size:
            content += f"\n... (truncated, {size} total bytes)"
        return content
    finally:
        await asyncio.to_thread(os.close, fd)


_BLOCK_SIGNATURE_RE = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?def\s+\w+|"
    r"class\s+\w+|"
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class)\s+\w+|"
    r"(?:pub\s+)?fn\s+\w+|"
    r"func\s+\w+|"
    r"impl\s+\w+"
    r")",
    re.MULTILINE,
)

def _block_name(line: str) -> str:
    match = re.search(r"\b(?:async\s+def|def|class|function|fn|func|impl)\s+(\w+)", line)
    return match.group(1) if match else ""


def _prune_python_source(source: str, query: str, max_lines: int) -> str:
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _prune_generic_source(source, query, max_lines)

    terms = [t.lower() for t in query.split() if len(t) > 2] if query.strip() else []

    def _matches(name: str) -> bool:
        if not terms:
            return True
        name_l = name.lower()
        return any(t in name_l for t in terms)

    def _text(node: ast.AST) -> str:
        start = int(getattr(node, "lineno", 1))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.decorator_list:
            start = min(d.lineno for d in node.decorator_list)
        lines = source.splitlines()
        return "\n".join(lines[start - 1 : getattr(node, "end_lineno", start)])

    blocks: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and _matches(node.name):
            blocks.append(_text(node))

    header: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            header.append(_text(node))

    out: list[str] = []
    budget = max_lines
    if header:
        header_block = "\n".join(header)
        header_lines = header_block.count("\n") + 1
        if header_lines <= budget:
            out.append(header_block)
            budget -= header_lines
    for block in blocks:
        block_lines = block.count("\n") + 1
        if block_lines > budget:
            continue
        out.append(block)
        budget -= block_lines
    return "\n\n".join(out)


def _prune_generic_source(source: str, query: str, max_lines: int) -> str:
    terms = [t.lower() for t in query.split() if len(t) > 2] if query.strip() else []
    lines = source.splitlines()
    sigs: list[tuple[int, str]] = [(i, ln) for i, ln in enumerate(lines) if _BLOCK_SIGNATURE_RE.match(ln)]
    if not sigs:
        return "\n".join(lines[:max_lines])

    wanted: list[tuple[int, int]] = []
    for i, (idx, line) in enumerate(sigs):
        name = _block_name(line).lower()
        if terms and not any(t in name for t in terms):
            continue
        indent = len(line) - len(line.lstrip())
        end = len(lines)
        for j in range(i + 1, len(sigs)):
            j_line = sigs[j][1]
            j_indent = len(j_line) - len(j_line.lstrip())
            if j_indent <= indent:
                end = sigs[j][0]
                break
        wanted.append((idx, end))

    preamble: list[str] = []
    for ln in lines[: sigs[0][0]][:12]:
        if ln.startswith(("import ", "use ", "require(", "const ", "let ", "var ", "#", "//", "/*", "*", "package ", "from ")):
            preamble.append(ln)

    out: list[str] = []
    budget = max_lines
    if preamble and len(preamble) <= budget:
        out.append("\n".join(preamble))
        budget -= len(preamble)
    for start, end in wanted:
        block_lines = end - start
        if block_lines > budget:
            continue
        out.append("\n".join(lines[start:end]))
        budget -= block_lines
    return "\n\n".join(out)


async def file_read_relevant(path: str, query: str = "", max_lines: int = 300) -> str:
    """Read only the relevant functions/classes matching a query (AST pruning).

    For small files (<= max_lines) the whole file is returned. For larger files
    only the matching top-level blocks plus the import header are kept, cutting
    token cost and noise for the LLM.
    """
    source = await _read_file(path)
    total = len(source.splitlines())
    if total <= max_lines:
        return source
    if path.lower().endswith(".py"):
        pruned = _prune_python_source(source, query, max_lines)
    else:
        pruned = _prune_generic_source(source, query, max_lines)
    pruned_lines = len(pruned.splitlines())
    if not pruned.strip():
        if query.strip():
            return f"# No relevant symbols found for query: {query}\n# File has {total} lines."
        head = "\n".join(source.splitlines()[:max_lines])
        return f"{head}\n... (pruned: {total} -> {pruned_lines} lines)"
    if pruned_lines >= total * 0.9:
        return source
    return f"{pruned}\n... (pruned: {total} -> {pruned_lines} lines)"


async def file_write(path: str, content: str) -> str:
    await _write_file(path, content)
    return f"Written {len(content)} bytes to {path}"


async def file_append(path: str, content: str) -> str:
    await _write_file(path, content, flags=os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    return f"Appended {len(content)} bytes to {path}"


async def file_edit(path: str, old_string: str, new_string: str) -> str:
    content = await _read_file(path)

    if old_string not in content:
        return f"[error] old_string not found in {path}"

    new_content = content.replace(old_string, new_string, 1)
    await _write_file(path, new_content)
    return f"Applied edit to {path} ({len(new_content)} bytes, {len(content) - len(new_content)} delta)"


async def file_list(path: str = ".", pattern: str = "*") -> str:
    p = _confine(path)
    exists = await asyncio.to_thread(p.exists)
    if not exists:
        msg = f"Directory not found: {p}"
        raise FileNotFoundError(msg)
    items: list[str] = []
    max_depth = 0
    for f in await asyncio.to_thread(lambda: list(p.glob(pattern))):
        if len(items) >= _MAX_LIST_ITEMS:
            items.append("... (truncated, too many files)")
            break
        kind = "📁" if await asyncio.to_thread(f.is_dir) else "📄"
        size = (await asyncio.to_thread(f.stat)).st_size if await asyncio.to_thread(f.is_file) else 0
        items.append(f"{kind} {f.name}  ({size} bytes)" if size else f"{kind} {f.name}")
        try:
            rel = f.relative_to(p)
            max_depth = max(max_depth, len(rel.parts))
        except ValueError:
            pass
    if max_depth > 10:
        items.append("... (truncated, depth limit reached)")
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
    msg = f"Not found: {p}"
    raise FileNotFoundError(msg)


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
    registry.register(
        ToolSpec(
            name="file_edit",
            description="Edit a file by replacing exact text (diff-safe, no full rewrite)",
            parameters={
                "path": {"type": "string", "description": "Path to the file", "required": True},
                "old_string": {"type": "string", "description": "Exact text to replace", "required": True},
                "new_string": {"type": "string", "description": "Replacement text", "required": True},
            },
            handler=file_edit,
            category="file",
        )
    )
    registry.register(
        ToolSpec(
            name="file_read_relevant",
            description="Read only the functions/classes of a file relevant to a query (AST pruning, "
            "keeps imports + matching blocks, drops the rest). Prefer over file_read for large files.",
            parameters={
                "path": {"type": "string", "description": "Path to the file", "required": True},
                "query": {"type": "string", "description": "What the task is about (symbol names)", "required": False},
                "max_lines": {"type": "integer", "description": "Max output lines", "required": False},
            },
            handler=file_read_relevant,
            category="file",
        )
    )
