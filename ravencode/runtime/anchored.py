from __future__ import annotations

import contextlib
from pathlib import Path

_ANCHORED_SUMMARY: str | None = None
_ANCHORED_PATH: Path = Path("data/sessions/anchored.md")


def set_anchored_path(path: str | Path) -> None:
    global _ANCHORED_PATH
    _ANCHORED_PATH = Path(path)


def _load() -> None:
    global _ANCHORED_SUMMARY
    _ANCHORED_SUMMARY = ""
    with contextlib.suppress(Exception):
        if _ANCHORED_PATH.is_file():
            _ANCHORED_SUMMARY = _ANCHORED_PATH.read_text(encoding="utf-8")


def _persist() -> None:
    with contextlib.suppress(Exception):
        _ANCHORED_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ANCHORED_PATH.write_text(_ANCHORED_SUMMARY or "", encoding="utf-8")


def anchored_summary() -> str:
    global _ANCHORED_SUMMARY
    if _ANCHORED_SUMMARY is None:
        _load()
    return _ANCHORED_SUMMARY or ""


def update_anchored_summary(text: str) -> str:
    global _ANCHORED_SUMMARY
    _ANCHORED_SUMMARY = text
    _persist()
    return f"Anchored summary updated ({len(text)} chars)"


def append_anchored_summary(text: str) -> str:
    global _ANCHORED_SUMMARY
    if _ANCHORED_SUMMARY is None:
        _load()
    if _ANCHORED_SUMMARY:
        _ANCHORED_SUMMARY += "\n" + text
    else:
        _ANCHORED_SUMMARY = text
    _persist()
    return f"Anchored summary appended ({len(text)} chars)"


def clear_anchored_summary() -> str:
    global _ANCHORED_SUMMARY
    _ANCHORED_SUMMARY = ""
    _persist()
    return "(anchored summary cleared)"
