from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .flags import FeatureFlag, flags

# Strangler Fig proxy — routes requests to either monolith or microservice
# In shadow mode, requests go to both for result comparison


class StranglerProxy:
    """Proxies API requests to microservice when feature flag is active.

    In shadow mode, both monolith and microservice responses are recorded,
    but the monolith response is returned to the client.
    """

    def __init__(self, service_name: str, microservice_url: str, feature_flag: FeatureFlag, shadow_flag: FeatureFlag):
        self._service_name = service_name
        self._microservice_url = microservice_url.rstrip("/")
        self._feature_flag = feature_flag
        self._shadow_flag = shadow_flag
        self._client = httpx.AsyncClient(timeout=30.0)

    async def proxy_or_call(
        self,
        method: str,
        path: str,
        monolith_fn: Any,
        body: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not flags.is_enabled(self._feature_flag) and not flags.is_enabled(self._shadow_flag):
            return await monolith_fn()  # type: ignore[no-any-return]

        url = f"{self._microservice_url}{path}"
        ms_response = await self._call_microservice(method, url, body, headers)

        if flags.is_enabled(self._shadow_flag):
            mono_response = await monolith_fn()
            self._compare(mono_response, ms_response, path)
            return mono_response  # type: ignore[no-any-return]

        return ms_response

    async def _call_microservice(
        self, method: str, url: str, body: dict[str, Any] | None, headers: dict[str, Any] | None
    ) -> dict[str, Any]:
        start = time.monotonic()
        try:
            if method.upper() == "GET":
                resp = await self._client.get(url, headers=headers)
            else:
                resp = await self._client.request(method, url, json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except Exception as e:
            from loguru import logger

            logger.warning("[strangler/{}] ms call failed: {}", self._service_name, e)
            raise
        finally:
            elapsed = (time.monotonic() - start) * 1000
            if elapsed > 500:
                from loguru import logger

                logger.warning("[strangler/{}] ms latency {}ms > 500ms", self._service_name, elapsed)

    def _compare(self, mono: dict[str, Any], ms: dict[str, Any], path: str):
        mono_str = json.dumps(mono, sort_keys=True, default=str)
        ms_str = json.dumps(ms, sort_keys=True, default=str)
        if mono_str != ms_str:
            from loguru import logger

            logger.warning(
                "[strangler/{}] mismatch on {}: monolith != microservice",
                self._service_name,
                path,
            )

    async def close(self):
        await self._client.aclose()
