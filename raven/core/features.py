from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

_FEATURES_PATH = Path(".raven") / "features.yaml"
_FALLBACK_PATH = Path("raven.yaml")


class FeatureFlags:
    """Config-driven feature toggles. Loaded from yaml, env, or defaults."""

    _instance: FeatureFlags | None = None

    def __init__(self) -> None:
        self.memory: bool = True
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
                    for key in [f for f in dir(flags) if not f.startswith("_")]:
                        if key in features:
                            setattr(flags, key, bool(features[key]))
                    logger.info("Feature flags loaded from {}", source)
                else:
                    logger.warning("'features' block in {} is not a dict, using defaults", source)
            except Exception:
                logger.opt(exception=True).warning("Failed to load feature flags from {}", source)
        else:
            logger.debug("No feature config found, using defaults")
        cls._instance = flags
        return flags

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


_ALL_FEATURES = [
    "memory", "skills", "dreaming", "planner",
    "browser", "delegation", "voice", "telemetry",
]


def _find_config() -> Path | None:
    for candidate in [_FEATURES_PATH, _FALLBACK_PATH]:
        if candidate.exists():
            return candidate
    return None
