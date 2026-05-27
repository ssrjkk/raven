from __future__ import annotations

import os
from enum import Enum

from loguru import logger


class FeatureFlag(str, Enum):
    """Feature flags for strangler fig migration.

    Each flag controls whether a monolith module delegates to its
    microservice counterpart. Flags are read from env vars with
    a default of False (monolith path, safe).
    """

    USE_AUTH_SERVICE = "use_auth_service"
    USE_MONITOR_SERVICE = "use_monitor_service"
    USE_RAG_SERVICE = "use_rag_service"
    USE_CODE_SERVICE = "use_code_service"
    USE_TASK_SERVICE = "use_task_service"
    USE_AGENT_SERVICE = "use_agent_service"
    USE_CHANNELS_SERVICE = "use_channels_service"

    # Shadow mode: write to both, read from monolith
    SHADOW_AUTH = "shadow_auth"
    SHADOW_MONITOR = "shadow_monitor"
    SHADOW_RAG = "shadow_rag"
    SHADOW_CODE = "shadow_code"
    SHADOW_TASK = "shadow_task"
    SHADOW_AGENT = "shadow_agent"


class FeatureFlagProvider:
    """Reads feature flags from environment variables.

    Convention: FF_<FLAG_NAME> = "true" enables the flag.
    """

    def __init__(self, prefix: str = "FF_"):
        self._prefix = prefix

    def is_enabled(self, flag: FeatureFlag) -> bool:
        return os.environ.get(f"{self._prefix}{flag.value}", "false").lower() == "true"

    def set(self, flag: FeatureFlag, value: bool):
        os.environ[f"{self._prefix}{flag.value}"] = "true" if value else "false"
        logger.info("[flags] {} = {}", flag.value, value)

    def summary(self) -> dict[str, bool]:
        return {f.value: self.is_enabled(f) for f in FeatureFlag}


flags = FeatureFlagProvider()
