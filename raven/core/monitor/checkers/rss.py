from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

from raven.core.http_client import client_manager
from raven.core.security.ssrf import validate_url

if TYPE_CHECKING:
    from raven.core.monitor.models import Monitor

_seen_guids: dict[str, set[str]] = {}
_seen_lock = asyncio.Lock()


async def _mark_seen(monitor_id: str, guid: str):
    async with _seen_lock:
        if monitor_id not in _seen_guids:
            _seen_guids[monitor_id] = set()
        _seen_guids[monitor_id].add(guid)


async def _is_seen(monitor_id: str, guid: str) -> bool:
    async with _seen_lock:
        return guid in _seen_guids.get(monitor_id, set())


async def check_rss(monitor: Monitor) -> str | None:
    url = monitor.config.get("target", monitor.target)
    error = validate_url(url)
    if error:
        return f"🔴 RSS check blocked: {error}"
    try:
        import feedparser

        resp = await client_manager.request("GET", url)
        raw_text = resp.text
        feed = feedparser.parse(raw_text)
    except Exception as exc:
        logger.error("RSS check failed for {}: {}", url, exc)
        return f"RSS check failed for {url}"

    new_entries: list[str] = []
    for entry in feed.entries[:10]:
        guid = entry.get("id", entry.get("link", ""))
        if not guid:
            continue
        if not await _is_seen(monitor.id, guid):
            await _mark_seen(monitor.id, guid)
            new_entries.append(entry.get("title", "(no title)"))

    if new_entries:
        return f"📰 New RSS entries from {url[:50]}:\n" + "\n".join(f"  • {t}" for t in new_entries[:5])

    return None
