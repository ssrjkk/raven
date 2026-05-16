from __future__ import annotations

from typing import TYPE_CHECKING

from raven.core.http_client import client_manager

if TYPE_CHECKING:
    from raven.core.monitor.models import Monitor


async def check_price(monitor: Monitor) -> str | None:
    coin_id = monitor.config.get("target", monitor.target).strip().lower()
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    try:
        data = await client_manager.get(url)
    except Exception:
        return None
    if not data or coin_id not in data:
        return None
    price = data[coin_id].get("usd")
    if price is None:
        return None
    threshold = monitor.config.get("threshold")
    if threshold is not None:
        if price >= float(threshold):
            return None
        return f"⚠️ {coin_id.upper()} price dropped to ${price:,.2f} (threshold: ${float(threshold):,.2f})"
    return None
