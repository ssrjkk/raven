from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.http_client import client_manager

if TYPE_CHECKING:
    from raven.core.monitor.models import Monitor

_seen_guids: dict[str, set[str]] = {}


def _mark_seen(monitor_id: str, guid: str):
    if monitor_id not in _seen_guids:
        _seen_guids[monitor_id] = set()
    _seen_guids[monitor_id].add(guid)


def _is_seen(monitor_id: str, guid: str) -> bool:
    return guid in _seen_guids.get(monitor_id, set())


async def check_rss(monitor: Monitor) -> str | None:
    url = monitor.config.get("target", monitor.target)
    try:
        import feedparser

        raw = await client_manager.get(url)
        if isinstance(raw, dict):
            raw_text = str(raw)
        elif isinstance(raw, str):
            raw_text = raw
        else:
            raw_text = str(raw)
        feed = feedparser.parse(raw_text)
    except Exception as exc:
        return f"🔴 RSS check failed for {url}: {exc}"

    new_entries: list[str] = []
    for entry in feed.entries[:10]:
        guid = entry.get("id", entry.get("link", ""))
        if not guid:
            continue
        if not _is_seen(monitor.id, guid):
            _mark_seen(monitor.id, guid)
            new_entries.append(entry.get("title", "(no title)"))

    if new_entries:
        return f"📰 New RSS entries from {url[:50]}:\n" + "\n".join(f"  • {t}" for t in new_entries[:5])

    return None
