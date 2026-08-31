from __future__ import annotations

import difflib
import re
from typing import Any

from ravencode.runtime.workspace import confine

_UNIFIED_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*$",
    re.MULTILINE,
)


def _parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:
    lines = diff_text.splitlines(keepends=True)
    hunks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        m = _UNIFIED_HUNK_RE.match(line)
        if m:
            current = {
                "old_start": int(m.group(1)),
                "old_count": int(m.group(2) or 1),
                "new_start": int(m.group(3)),
                "new_count": int(m.group(4) or 1),
                "lines": [],
            }
            hunks.append(current)
        elif current is not None:
            current["lines"].append(line)
    return hunks


def apply_patch(path: str, diff_text: str) -> str:
    try:
        p = confine(path)
    except PermissionError as exc:
        return f"[error] {exc}"
    if not p.is_file():
        return f"[error] file not found: {path}"
    original = p.read_text(encoding="utf-8")
    original_lines = original.splitlines(keepends=True)
    hunks = _parse_unified_diff(diff_text)
    if not hunks:
        return "[error] no valid hunks in diff"
    result = list(original_lines)
    offset = 0
    for hunk in hunks:
        old_start = hunk["old_start"] - 1 + offset
        new_lines: list[str] = []
        ri = old_start
        for diff_line in hunk["lines"]:
            if not diff_line:
                continue
            prefix = diff_line[0]
            content = diff_line[1:]
            if prefix in (" ", "-"):
                if ri >= len(result) or result[ri] != content:
                    return f"[error] context mismatch at line {ri + 1}"
                ri += 1
                if prefix == " ":
                    new_lines.append(content)
            elif prefix == "+":
                new_lines.append(content)
        if ri - old_start == 0:
            return "[error] no valid hunks in diff"
        result[old_start:ri] = new_lines
        offset += len(new_lines) - (ri - old_start)
    p.write_text("".join(result), encoding="utf-8")
    return f"[ok] applied patch to {path} ({len(hunks)} hunks)"


def smart_edit(
    path: str,
    *,
    old_text: str | None = None,
    new_text: str | None = None,
    insert_after: str | None = None,
    insert_before: str | None = None,
    append: bool = False,
) -> str:
    try:
        p = confine(path)
    except PermissionError as exc:
        return f"[error] {exc}"
    if not p.is_file():
        return f"[error] file not found: {path}"
    content = p.read_text(encoding="utf-8")

    if old_text is not None and new_text is not None:
        if old_text not in content:
            return f"[error] old_text not found in {path}"
        count = content.count(old_text)
        if count > 1:
            return f"[error] {count} occurrences — provide more context"
        modified = content.replace(old_text, new_text, 1)
        p.write_text(modified, encoding="utf-8")
        return f"[ok] replaced text in {path}"

    if insert_after is not None and new_text is not None:
        if insert_after not in content:
            return f"[error] insert_after not found in {path}"
        modified = content.replace(insert_after, insert_after + new_text, 1)
        p.write_text(modified, encoding="utf-8")
        return f"[ok] inserted after in {path}"

    if insert_before is not None and new_text is not None:
        if insert_before not in content:
            return f"[error] insert_before not found in {path}"
        modified = content.replace(insert_before, new_text + insert_before, 1)
        p.write_text(modified, encoding="utf-8")
        return f"[ok] inserted before in {path}"

    if append and new_text is not None:
        with p.open("a", encoding="utf-8") as f:
            f.write(new_text)
        return f"[ok] appended to {path}"

    return "[error] provide old_text+new_text or insert_after/new_text+insert_before or append"


def compute_patch(original: str, modified: str, path: str = "file") -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            modified.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )


async def patch_file(path: str, diff_text: str) -> str:
    return apply_patch(path, diff_text)


async def smart_edit_tool(path: str, **kwargs: Any) -> str:
    return smart_edit(path, **kwargs)
