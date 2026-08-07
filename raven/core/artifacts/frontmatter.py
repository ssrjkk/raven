"""YAML frontmatter parsing for artifact files."""

from __future__ import annotations

from typing import Any

import yaml
from loguru import logger

_FM_DELIMITER = "---"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``text`` into (meta, body). Accepts ``---`` YAML frontmatter.

    Files without frontmatter return (empty dict, whole text).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM_DELIMITER:
        return {}, text
    closing: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FM_DELIMITER:
            closing = idx
            break
    if closing is None:
        return {}, text
    meta: dict[str, Any] = {}
    block = "\n".join(lines[1:closing])
    try:
        parsed = yaml.safe_load(block)
        if isinstance(parsed, dict):
            meta = parsed
    except yaml.YAMLError as exc:
        logger.debug("frontmatter parse failed: {}", exc)
    body = "\n".join(lines[closing + 1 :]).strip()
    return meta, body
