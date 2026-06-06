from __future__ import annotations

from typing import Any

import httpx

from raven.core.monitor.models import Monitor


async def check_price(monitor: Monitor) -> dict[str, Any]:
    target = monitor.target.strip().lower()
    provider = monitor.config.get("provider", "coingecko")

    if provider == "coingecko":
        return await _check_coingecko(target, monitor)
    elif provider == "yahoo":
        return await _check_yahoo(target, monitor)
    elif provider == "custom":
        return await _check_custom_url(target, monitor)
    else:
        return {"error": f"Unknown provider: {provider}"}


async def _check_coingecko(symbol: str, monitor: Monitor) -> dict[str, Any]:
    coin_map = {
        "bitcoin": "bitcoin",
        "btc": "bitcoin",
        "ethereum": "ethereum",
        "eth": "ethereum",
        "solana": "solana",
        "sol": "solana",
        "cardano": "cardano",
        "ada": "cardano",
        "ripple": "ripple",
        "xrp": "ripple",
        "dogecoin": "dogecoin",
        "doge": "dogecoin",
    }
    coin_id = coin_map.get(symbol, symbol)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"

    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(url)
        data = resp.json()

    if coin_id not in data:
        return {"error": f"Symbol {symbol} not found", "price": None}

    price = data[coin_id]["usd"]
    return {
        "price": price,
        "symbol": symbol,
        "currency": "USD",
        "source": "coingecko",
    }


async def _check_yahoo(symbol: str, monitor: Monitor) -> dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(url)
        data = resp.json()

    try:
        price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        return {"price": price, "symbol": symbol, "source": "yahoo"}
    except (KeyError, IndexError):
        return {"error": f"Symbol {symbol} not found on Yahoo", "price": None}


async def _check_custom_url(url: str, monitor: Monitor) -> dict[str, Any]:
    json_path = monitor.config.get("json_path", "")
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(url)
        data = resp.json()

    if json_path:
        try:
            parts = json_path.split(".")
            val = data
            for p in parts:
                if p.isdigit():
                    val = val[int(p)]
                else:
                    val = val[p]
            return {"price": float(val), "source": "custom", "url": url}
        except (KeyError, IndexError, ValueError, TypeError):
            return {"error": f"json_path {json_path} not found", "price": None}

    return {"price": None, "source": "custom", "raw": str(data)[:500]}
