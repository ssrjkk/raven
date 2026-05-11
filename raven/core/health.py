from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable


@dataclass
class HealthCheck:
    name: str
    check: Callable[[], Awaitable[bool | str]]
    timeout: float = 5.0
    critical: bool = True
    last_check: float = 0.0
    last_status: bool = True
    last_detail: str = ""
    cache_ttl: float = 10.0


class HealthRegistry:
    def __init__(self):
        self._checks: dict[str, HealthCheck] = {}
        self._lock = asyncio.Lock()

    def register(self, name: str, check: Callable[[], Awaitable[bool | str]], timeout: float = 5.0, critical: bool = True):
        self._checks[name] = HealthCheck(name=name, check=check, timeout=timeout, critical=critical)

    async def check_all(self) -> dict:
        results = {}
        all_ok = True
        async with self._lock:
            for name, hc in self._checks.items():
                if time.monotonic() - hc.last_check < hc.cache_ttl:
                    results[name] = {"ok": hc.last_status, "detail": hc.last_detail}
                    if not hc.last_status:
                        all_ok = False
                    continue
                try:
                    result = await asyncio.wait_for(hc.check(), timeout=hc.timeout)
                    if isinstance(result, bool):
                        hc.last_status = result
                        hc.last_detail = ""
                    else:
                        hc.last_status = True
                        hc.last_detail = str(result)
                except asyncio.TimeoutError:
                    hc.last_status = False
                    hc.last_detail = "timeout"
                except Exception as e:
                    hc.last_status = False
                    hc.last_detail = str(e)
                hc.last_check = time.monotonic()
                results[name] = {"ok": hc.last_status, "detail": hc.last_detail}
                if not hc.last_status:
                    all_ok = False
        return {"status": "ok" if all_ok else "degraded", "checks": results, "timestamp": time.time()}

    async def check_liveness(self) -> dict:
        return await self.check_all()

    async def check_readiness(self) -> dict:
        results = {}
        all_ok = True
        async with self._lock:
            for name, hc in self._checks.items():
                if not hc.critical:
                    continue
                if time.monotonic() - hc.last_check > hc.cache_ttl * 2:
                    try:
                        result = await asyncio.wait_for(hc.check(), timeout=hc.timeout)
                        hc.last_status = result if isinstance(result, bool) else True
                        hc.last_detail = "" if isinstance(result, bool) else str(result)
                    except Exception as e:
                        hc.last_status = False
                        hc.last_detail = str(e)
                    hc.last_check = time.monotonic()
                results[name] = {"ok": hc.last_status, "detail": hc.last_detail}
                if not hc.last_status:
                    all_ok = False
        return {"status": "ok" if all_ok else "degraded", "checks": results, "timestamp": time.time()}


health = HealthRegistry()
