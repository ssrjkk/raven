from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any

from loguru import logger

from ravencode.runtime.undo import get_undo_manager
from ravencode.runtime.workspace import confine

_UNIFIED_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*$",
    re.MULTILINE,
)
_MISSING_NEWLINE = "\\ No newline at end of file"


def _write_atomic(path: Path, payload: str) -> None:
    """Replace *path* in one step, byte-for-byte as given.

    ``write_text`` truncates the target before a single byte is written, so an interrupted patch
    used to leave a half-written source file behind - unrecoverable, because apply_patch recorded
    no undo entry either. ``newline=""`` keeps the file's own line endings instead of the host's.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _bare(line: str) -> str:
    """The line's text without its trailing ending, so CRLF and LF files compare alike."""
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _is_file_header(lines: list[str], index: int) -> bool:
    """A real "--- " header is followed by its "+++" and an "@@"; a removed "-- x" line is not."""
    following = [lines[i].rstrip("\r\n") for i in range(index + 1, min(index + 3, len(lines)))]
    return len(following) == 2 and following[0].startswith("+++ ") and bool(
        _UNIFIED_HUNK_RE.match(following[1])
    )


def _patch_targets_multiple_files(diff_text: str) -> bool:
    lines = diff_text.splitlines(keepends=True)
    return sum(1 for i, line in enumerate(lines) if line.startswith("--- ") and _is_file_header(lines, i)) > 1


def _parse_unified_diff(diff_text: str) -> list[dict[str, Any]]:
    lines = diff_text.splitlines(keepends=True)
    hunks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for index, line in enumerate(lines):
        m = _UNIFIED_HUNK_RE.match(line)
        if m:
            current = {
                "old_start": int(m.group(1)),
                "old_count": int(m.group(2)) if m.group(2) is not None else 1,
                "new_start": int(m.group(3)),
                "new_count": int(m.group(4)) if m.group(4) is not None else 1,
                "lines": [],
            }
            hunks.append(current)
            continue
        if current is None:
            continue
        if line.startswith("--- ") and _is_file_header(lines, index):
            break  # a second file's header ends this one's hunks
        current["lines"].append(line)
    return hunks


def _split_hunk_body(hunk: dict[str, Any]) -> tuple[list[str], list[str]] | str:
    """Return the (old, new) line texts the hunk carries, or an error message."""
    old: list[str] = []
    new: list[str] = []
    for diff_line in hunk["lines"]:
        prefix = diff_line[:1]
        if prefix == "":
            continue
        content = diff_line[1:]
        if prefix == " ":
            old.append(content)
            new.append(content)
        elif prefix == "-":
            old.append(content)
        elif prefix == "+":
            new.append(content)
        elif diff_line.startswith(_MISSING_NEWLINE):
            continue
        else:
            return (
                f"[error] malformed line {diff_line!r} in the hunk at line {hunk['old_start']}"
            )
    if len(old) != hunk["old_count"] or len(new) != hunk["new_count"]:
        return (
            f"[error] hunk at line {hunk['old_start']} declares -{hunk['old_count']} "
            f"+{hunk['new_count']} but carries {len(old)}/{len(new)}"
        )
    return old, new


def apply_patch(path: str, diff_text: str) -> str:
    try:
        p = confine(path)
    except PermissionError as exc:
        logger.debug("[diff] access denied for {}: {}", path, exc)
        return f"[error] {exc}"
    if not p.is_file():
        return f"[error] file not found: {path}"
    try:
        # Path.read_text's newline= is 3.13+; this runs on 3.11 and 3.12 too.
        with p.open("r", encoding="utf-8", newline="") as f:
            original = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return f"[error] cannot read {path}: {exc}"

    if _patch_targets_multiple_files(diff_text):
        return "[error] multi-file diffs are not supported; patch one file at a time"
    hunks = _parse_unified_diff(diff_text)
    if not hunks:
        return "[error] no valid hunks in diff"

    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines(keepends=True)
    prepared: list[tuple[int, list[str], list[str]]] = []
    for hunk in hunks:
        body = _split_hunk_body(hunk)
        if isinstance(body, str):
            return body
        old, new = body
        # old_count == 0 means "insert after line old_start"; otherwise old_start is 1-based and
        # inclusive, which is the whole difference the old loop conflated.
        at = hunk["old_start"] if hunk["old_count"] == 0 else hunk["old_start"] - 1
        prepared.append((at, old, new))

    # Bottom-up: editing the tail first leaves every earlier index untouched, so hunks apply in
    # any order and one drifting offset cannot silently rewrite the wrong line.
    for at, old, new in sorted(prepared, key=lambda item: item[0], reverse=True):
        window = lines[at : at + len(old)]
        if len(window) != len(old) or [_bare(w) for w in window] != [_bare(o) for o in old]:
            return f"[error] context mismatch at line {at + 1}"
        lines[at : at + len(old)] = [f"{_bare(c)}{newline}" for c in new]

    if lines and not original.endswith("\n"):
        lines[-1] = _bare(lines[-1])  # keep the file's missing-final-newline property
    modified = "".join(lines)
    get_undo_manager().record(str(p), original, modified, "apply_patch")
    try:
        _write_atomic(p, modified)
    except OSError as exc:
        return f"[error] write failed for {path}: {exc}"
    return f"[ok] applied patch to {path} ({len(hunks)} hunks)"


def _store(p: Path, path: str, content: str, verb: str) -> str:
    try:
        _write_atomic(p, content)
    except OSError as exc:
        return f"[error] write failed for {path}: {exc}"
    return f"[ok] {verb} in {path}"


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
        logger.debug("[diff] access denied for {}: {}", path, exc)
        return f"[error] {exc}"
    if not p.is_file():
        return f"[error] file not found: {path}"
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            original = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        return f"[error] cannot read {path}: {exc}"
    content = original

    if old_text is not None and new_text is not None:
        if old_text not in content:
            return f"[error] old_text not found in {path}"
        count = content.count(old_text)
        if count > 1:
            return f"[error] {count} occurrences — provide more context"
        modified = content.replace(old_text, new_text, 1)
        get_undo_manager().record(str(p), original, modified, "smart_edit")
        return _store(p, path, modified, "replaced text")

    if insert_after is not None and new_text is not None:
        if insert_after not in content:
            return f"[error] insert_after not found in {path}"
        modified = content.replace(insert_after, insert_after + new_text, 1)
        get_undo_manager().record(str(p), original, modified, "smart_edit")
        return _store(p, path, modified, "inserted after")

    if insert_before is not None and new_text is not None:
        if insert_before not in content:
            return f"[error] insert_before not found in {path}"
        modified = content.replace(insert_before, new_text + insert_before, 1)
        get_undo_manager().record(str(p), original, modified, "smart_edit")
        return _store(p, path, modified, "inserted before")

    if append and new_text is not None:
        modified = content + new_text
        get_undo_manager().record(str(p), original, modified, "smart_edit")
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
