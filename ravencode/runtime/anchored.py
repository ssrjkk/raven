from __future__ import annotations

_ANCHORED_SUMMARY: str = ""


def anchored_summary() -> str:
    return _ANCHORED_SUMMARY


def update_anchored_summary(text: str) -> str:
    global _ANCHORED_SUMMARY
    _ANCHORED_SUMMARY = text
    return f"Anchored summary updated ({len(text)} chars)"


def append_anchored_summary(text: str) -> str:
    global _ANCHORED_SUMMARY
    if _ANCHORED_SUMMARY:
        _ANCHORED_SUMMARY += "\n" + text
    else:
        _ANCHORED_SUMMARY = text
    return f"Anchored summary appended ({len(text)} chars)"


def clear_anchored_summary() -> str:
    global _ANCHORED_SUMMARY
    _ANCHORED_SUMMARY = ""
    return "(anchored summary cleared)"
