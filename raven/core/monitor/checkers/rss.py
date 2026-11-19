from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.http_client import client_manager
from raven.core.security.ssrf import validate_url

if TYPE_CHECKING:
    from raven.core.monitor.models import Monitor
    from raven.core.monitor.store import MonitorStore

_MAX_ENTRIES = 10
"""How much of the feed one poll reads; the alert names at most five of those."""


def _feed_entries(feed: Any) -> list[tuple[str, str]]:
    """`(guid, title)` for the polled slice in feed order; an entry with no identity cannot be deduped."""
    entries: list[tuple[str, str]] = []
    for entry in feed.entries[:_MAX_ENTRIES]:
        guid = entry.get("id", entry.get("link", ""))
        if not guid:
            continue
        entries.append((guid, entry.get("title", "(no title)")))
    return entries


async def check_rss(monitor: Monitor, store: MonitorStore) -> str | None:
    """Report the feed entries this monitor has not been shown before.

    The seen set is `rss_seen_items`, one row per (entry, monitor), so a gateway restart reads the same
    rows back instead of treating the whole feed as new; the row's `seen_at` is what the retention sweep
    ages and caps, which makes the memory of a past entry last as long as the operator's telemetry window
    rather than a TTL baked in here.

    A monitor with no rows yet is baselined: its current entries are recorded and nothing is reported.
    Without that rule the first poll after this table existed — and the first poll of every monitor
    created from now on — would alert the entire feed as though it had just arrived.
    """
    url = monitor.config.get("target", monitor.target)
    error = validate_url(url)
    if error:
        return f"🔴 RSS check blocked: {error}"
    try:
        import feedparser

        resp = await client_manager.request("GET", url)
        feed = feedparser.parse(resp.text)
    except Exception as exc:
        logger.error("RSS check failed for {}: {}", url, exc)
        return f"RSS check failed for {url}"

    entries = _feed_entries(feed)
    if not await store.rss_has_seen_items(monitor.id):
        for guid, _title in entries:
            await store.rss_mark_seen(monitor.id, guid)
        logger.info("RSS monitor {} baselined {} feed entries", monitor.id, len(entries))
        return None

    new_titles = [title for guid, title in entries if await store.rss_mark_seen(monitor.id, guid)]
    if new_titles:
        return f"📰 New RSS entries from {url[:50]}:\n" + "\n".join(f"  • {t}" for t in new_titles[:5])

    return None
