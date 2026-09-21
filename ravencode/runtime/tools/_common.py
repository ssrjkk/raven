from __future__ import annotations

import asyncio
import difflib

from ravencode.runtime.undo import get_undo_manager
from ravencode.runtime.workspace import (
    confine as _confine,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _compute_diff(original: str, modified: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
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
    if p.is_file():
        original = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="replace")
        get_undo_manager().record(str(p), original, content, "write")
    else:
        get_undo_manager().record(str(p), "", content, "write")
    await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(p.write_text, content, encoding="utf-8")
