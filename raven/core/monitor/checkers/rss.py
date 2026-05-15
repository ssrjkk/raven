from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

from raven.core.http_client import client_manager

if TYPE_CHECKING:
    from raven.core.monitor.models import CheckResult, Monitor
    from raven.core.monitor.store import MonitorStore


def check_rss_feed(monitor: Monitor, store: MonitorStore) -> CheckResult:
    from raven.core.monitor.models import CheckResult

    url = monitor.config.get("target", monitor.target)
    try:
        import asyncio
        data = asyncio.run(client_manager.get(url))
        items = data if isinstance(data, list) else data.get("items", data.get("entries", [])) if isinstance(data, dict) else []
        new_items = 0
        for item in items:
            guid = item.get("id", item.get("guid", item.get("link", "")))
            if guid:
                seen = _is_seen(monitor.id, guid)
                if not seen:
                    new_items += 1
        return CheckResult(
            status="up",
            checked_at=time.time(),
            triggered=new_items > 0,
        )
    except Exception as e:
        return CheckResult(
            status="down",
            checked_at=time.time(),
            triggered=False,
            error=str(e),
        )


def _mark_seen(monitor_id: str, guid: str):
    from raven.core.config import settings
    conn = sqlite3.connect(str(settings.resolved_db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO rss_seen_items (guid, monitor_id) VALUES (?, ?)",
            (guid, monitor_id),
        )
        conn.commit()
    finally:
        conn.close()


def _is_seen(monitor_id: str, guid: str) -> bool:
    from raven.core.config import settings
    conn = sqlite3.connect(str(settings.resolved_db_path))
    try:
        row = conn.execute(
            "SELECT 1 FROM rss_seen_items WHERE guid = ? AND monitor_id = ?",
            (guid, monitor_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
