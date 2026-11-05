from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

_FEATURES_PATH = Path(".raven") / "features.yaml"
_FALLBACK_PATH = Path("raven.yaml")


class FeatureFlags:
    """Feature toggles read from `raven.yaml` / `.raven/features.yaml`, then overridden by
    the `RAVEN_FEATURE_*` variables listed in `_ENV_FLAGS`."""

    _instance: FeatureFlags | None = None

    def __init__(self) -> None:
        self.skills: bool = True
        self.dreaming: bool = False
        self.planner: bool = True
        self.browser: bool = False
        self.delegation: bool = True
        self.voice: bool = False
        self.telemetry: bool = False

    @classmethod
    def load(cls, path: Path | None = None) -> FeatureFlags:
        flags = cls()
        source = path or _find_config()
        if source and source.exists():
            try:
                raw: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8"))
                features = raw.get("features", {}) if isinstance(raw, dict) else raw
                if isinstance(features, dict):
                    for key, value in features.items():
                        if key not in _ALL_FEATURES:
                            logger.warning("Unknown feature flag {} in {}, ignored", key, source)
                            continue
                        setattr(flags, key, bool(value))
                    logger.info("Feature flags loaded from {}", source)
                else:
                    logger.warning("'features' block in {} is not a dict, using defaults", source)
            except Exception:
                logger.opt(exception=True).warning("Failed to load feature flags from {}", source)
        else:
            logger.debug("No feature config found, using defaults")
        flags.apply_env()
        cls._instance = flags
        return flags

    def apply_env(self) -> None:
        """Override every flag named in the environment; the environment has the last word."""
        for name, env_var in _ENV_FLAGS.items():
            raw = os.environ.get(env_var, "").strip().lower()
            if not raw:
                continue
            if raw in _TRUTHY:
                setattr(self, name, True)
            elif raw in _FALSY:
                setattr(self, name, False)
            else:
                logger.warning("{}={} is not an on/off value, keeping {}", env_var, raw, getattr(self, name))

    @classmethod
    def get(cls) -> FeatureFlags:
        if cls._instance is None:
            cls._instance = cls.load()
        return cls._instance

    def is_enabled(self, name: str) -> bool:
        return bool(getattr(self, name, False))

    def enabled_list(self) -> list[str]:
        return [k for k in _ALL_FEATURES if getattr(self, k, False)]

    def to_dict(self) -> dict[str, bool]:
        return {k: getattr(self, k, False) for k in _ALL_FEATURES}


# One environment name per flag, so the list of toggles and the list of switches an operator
# can set cannot drift apart. Every name here is consulted somewhere in the code - the guard
# in tests/test_feature_flags.py fails the build if one ever stops being.
_ENV_FLAGS: dict[str, str] = {
    "skills": "RAVEN_FEATURE_SKILLS",
    "dreaming": "RAVEN_FEATURE_DREAMING",
    "planner": "RAVEN_FEATURE_PLANNER",
    "browser": "RAVEN_FEATURE_BROWSER",
    "delegation": "RAVEN_FEATURE_DELEGATION",
    "voice": "RAVEN_FEATURE_VOICE",
    "telemetry": "RAVEN_FEATURE_TELEMETRY",
}

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})

_ALL_FEATURES = list(_ENV_FLAGS)


def env_flag_names() -> dict[str, str]:
    """The environment variable that overrides each flag."""
    return dict(_ENV_FLAGS)


def _find_config() -> Path | None:
    for candidate in [_FEATURES_PATH, _FALLBACK_PATH]:
        if candidate.exists():
            return candidate
    return None
