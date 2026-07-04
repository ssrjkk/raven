from __future__ import annotations

import threading
import time

from raven.core.config import settings


class TierLimits:
    def __init__(self, rpd: int, rpm: int, concurrent: int):
        self.rpd = rpd
        self.rpm = rpm
        self.concurrent = concurrent


LIMITS: dict[str, TierLimits] = {
    "free": TierLimits(
        rpd=settings.tier_free_rpd,
        rpm=settings.tier_free_rpm,
        concurrent=settings.tier_free_concurrent,
    ),
    "pro": TierLimits(
        rpd=settings.tier_pro_rpd,
        rpm=settings.tier_pro_rpm,
        concurrent=settings.tier_pro_concurrent,
    ),
    "enterprise": TierLimits(rpd=999_999, rpm=9_999, concurrent=999),
}


class TierStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._user_tier: dict[str, str] = {}
        self._daily: dict[str, str] = {}
        self._minute: dict[str, tuple[int, float]] = {}
        self._concurrent: dict[str, int] = {}

    def get_tier(self, user_id: str) -> str:
        with self._lock:
            return self._user_tier.get(user_id, settings.tier_default)

    def set_tier(self, user_id: str, tier: str):
        if tier not in LIMITS:
            raise ValueError(f"Unknown tier: {tier}")
        with self._lock:
            self._user_tier[user_id] = tier

    def check(self, user_id: str) -> tuple[bool, str]:
        tier = self.get_tier(user_id)
        limits = LIMITS.get(tier, LIMITS["free"])
        now = time.time()
        day_key = f"{user_id}:{time.strftime('%Y%m%d', time.localtime(now))}"
        min_key = f"{user_id}:{int(now // 60)}"

        with self._lock:
            # Daily
            day_val = int(self._daily.get(day_key, "0"))
            if day_val >= limits.rpd:
                return False, f"daily limit ({limits.rpd}) exceeded for tier '{tier}'"
            self._daily[day_key] = str(day_val + 1)

            # Per-minute
            raw = self._minute.get(min_key)
            if raw is None or int(raw[1]) != int(now // 60):
                self._minute[min_key] = (0, int(now // 60))
                raw = (0, int(now // 60))
            if raw[0] >= limits.rpm:
                return False, f"rate limit ({limits.rpm}/min) exceeded for tier '{tier}'"
            self._minute[min_key] = (raw[0] + 1, raw[1])

            # Concurrent
            cur = self._concurrent.get(user_id, 0)
            if cur >= limits.concurrent:
                return False, f"concurrent limit ({limits.concurrent}) exceeded for tier '{tier}'"
            self._concurrent[user_id] = cur + 1

        return True, ""

    def release(self, user_id: str):
        with self._lock:
            cur = self._concurrent.get(user_id, 0)
            if cur > 0:
                self._concurrent[user_id] = cur - 1


tier_store = TierStore()
