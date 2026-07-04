from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx
from loguru import logger

from raven.core.watermark import user_agent as _watermark_ua


class HTTPClientPool:
    _instance: HTTPClientPool | None = None

    def __init__(self):
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    def get_instance(cls) -> HTTPClientPool:
        if cls._instance is None:
            cls._instance = HTTPClientPool()
        return cls._instance

    async def get_client(
        self, base_url: str = "", timeout: float = 15.0, max_connections: int = 50
    ) -> httpx.AsyncClient:
        key = f"{base_url}|{timeout}"
        async with self._lock:
            if key not in self._clients or self._clients[key].is_closed:
                limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections // 2)
                self._clients[key] = httpx.AsyncClient(
                    base_url=base_url,
                    timeout=timeout,
                    limits=limits,
                    headers={"User-Agent": _watermark_ua()},
                )
            return self._clients[key]

    async def close_all(self):
        async with self._lock:
            for _key, client in self._clients.items():
                with contextlib.suppress(ConnectionError, asyncio.TimeoutError):
                    await client.aclose()
            self._clients.clear()
            self._closed = True
            logger.info("HTTP client pool closed ({} connections freed)", len(self._clients))

    async def health_check(self) -> bool:
        return not self._closed


class ClientManager:
    def __init__(self):
        self._pool = HTTPClientPool.get_instance()

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = await self._pool.get_client()
        return await client.request(method, url, **kwargs)

    async def post(
        self, url: str, json: dict[str, Any] | None = None, headers: dict[str, Any] | None = None, timeout: float = 15.0
    ) -> dict[str, Any]:
        client = await self._pool.get_client(timeout=timeout)
        resp = await client.post(url, json=json, headers=headers or {})
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def get(self, url: str, headers: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        client = await self._pool.get_client(timeout=timeout)
        resp = await client.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    async def close(self):
        await self._pool.close_all()


client_manager = ClientManager()
