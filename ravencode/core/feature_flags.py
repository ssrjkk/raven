from __future__ import annotations

import os

from loguru import logger

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


class FeatureFlags:
    def __init__(self) -> None:
        # Every flag here is consulted by code; tests/test_feature_flags.py fails the build
        # if a flag stops being read anywhere. Bitbucket has no integration in this tree at all.
        self._flags: dict[str, bool] = {
            "redis_rate_limiter": False,
        }
        self._load_from_env()

    def _load_from_env(self) -> None:
        prefix = "FF_"
        for key in self._flags:
            env_val = os.getenv(f"{prefix}{key.upper()}")
            if env_val is None:
                continue
            value = env_val.strip().lower()
            if value in _TRUTHY:
                self._flags[key] = True
            elif value in _FALSY:
                self._flags[key] = False
            else:
                logger.warning(
                    "FF_{}={} is not an on/off value, keeping {}", key.upper(), env_val, self._flags[key]
                )

    def is_enabled(self, flag: str, default: bool = False) -> bool:
        return self._flags.get(flag, default)

    def set(self, flag: str, value: bool) -> None:
        self._flags[flag] = value

    def all_flags(self) -> dict[str, bool]:
        return dict(self._flags)


feature_flags = FeatureFlags()
