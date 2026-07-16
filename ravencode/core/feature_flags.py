from __future__ import annotations

import os


class FeatureFlags:
    def __init__(self) -> None:
        self._flags: dict[str, bool] = {
            "new_planner_v2": False,
            "claude_3_opus": True,
            "bitbucket_webhooks": False,
            "redis_rate_limiter": False,
        }
        self._load_from_env()

    def _load_from_env(self) -> None:
        prefix = "FF_"
        for key in self._flags:
            env_val = os.getenv(f"{prefix}{key.upper()}")
            if env_val is not None:
                self._flags[key] = env_val.lower() in ("1", "true", "yes")

    def is_enabled(self, flag: str, default: bool = False) -> bool:
        return self._flags.get(flag, default)

    def set(self, flag: str, value: bool) -> None:
        self._flags[flag] = value

    def all_flags(self) -> dict[str, bool]:
        return dict(self._flags)


feature_flags = FeatureFlags()
