from __future__ import annotations

from typing import Any

import httpx

from raven.core.monitor.models import Monitor


async def check_rss(monitor: Monitor) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.get(monitor.target)
        content = resp.text

    posts = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(content)

        namespaces = {"": "", "atom": "http://www.w3.org/2005/Atom"}
        ns = {}
        for event, elem in ET.iterparse(monitor.target, events=("start-ns",)):
            if event == "start-ns":
                prefix, uri = elem
                ns[prefix or "default"] = uri

        items = root.findall(".//item") or root.findall(".//atom:entry", namespaces)
        for item in items[:20]:
            title = _find_text(item, "title", ns)
            link = _find_text(item, "link", ns)
            pubdate = _find_text(item, "pubDate", ns) or _find_text(item, "updated", ns) or _find_text(item, "published", ns)
            posts.append({
                "title": title or "(no title)",
                "link": link or "",
                "published": pubdate or "",
            })

        latest_item = root.find(".//item") or root.find(".//atom:entry", namespaces)
        last_build = _find_text(root, "lastBuildDate", ns) or _find_text(root, "updated", ns) or ""

        return {
            "feed_count": len(posts),
            "latest_title": posts[0]["title"] if posts else "",
            "latest_link": posts[0]["link"] if posts else "",
            "last_build": last_build,
            "titles": [p["title"] for p in posts],
        }
    except Exception as e:
        return {"error": f"RSS parse failed: {e}", "feed_count": 0}


def _find_text(parent, tag, namespaces: dict) -> str | None:
    for ns_prefix, ns_uri in namespaces.items():
        if ns_prefix:
            prefixed = f"{{{ns_uri}}}{tag}"
            elem = parent.find(prefixed)
            if elem is not None and elem.text:
                return elem.text
    if namespaces.get("default"):
        prefixed = f"{{{namespaces['default']}}}{tag}"
        elem = parent.find(prefixed)
        if elem is not None and elem.text:
            return elem.text
    elem = parent.find(tag)
    if elem is not None:
        return elem.text
    return None
