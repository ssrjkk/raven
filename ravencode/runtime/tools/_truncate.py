from __future__ import annotations

import hashlib
import time

from loguru import logger

from ravencode.runtime.workspace import (
    _get_workspace,
)


def _spill_output(text: str) -> str | None:
    """Persist a large tool result inside the workspace; returns path or None."""
    try:
        d = _get_workspace() / ".raven" / "spill"
        d.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:10]  # noqa: S324
        path = d / f"tool_{int(time.time())}_{digest}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)
    except Exception as exc:
        logger.debug("tool output spill failed: {}", exc)
        return None




def smart_truncate(text: str, limit: int = 10_000) -> str:
    """Middle-out truncation with disk spill for oversized tool results.

    Models need both ends of an output: beginnings explain what happened,
    endings carry conclusions. The middle is dropped and the full text is
    saved inside the workspace so the agent can `read` the rest on demand.
    """
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    note = f"\n\n[... {len(text) - limit} chars truncated ...]"
    spilled = _spill_output(text)
    if spilled:
        note += f"\n[full output saved to {spilled} — use read to inspect the middle part]"
    return text[:head] + note + "\n" + text[-tail:]
