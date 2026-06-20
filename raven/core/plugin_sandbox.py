from __future__ import annotations

from enum import StrEnum
from typing import Any

from loguru import logger


class Capability(StrEnum):
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    BROWSER = "browser"
    CODE_EXEC = "code_exec"
    API_CALL = "api_call"
    LLM = "llm"
    MEMORY = "memory"
    AUDIO = "audio"
    IMAGE = "image"


class PluginSandbox:
    def __init__(self):
        self._global_deny: set[str] = set()
        self._per_plugin: dict[str, set[str]] = {}

    def check(self, plugin_name: str, capability: str) -> bool:
        if capability in self._global_deny:
            logger.warning("[sandbox] {} blocked by global deny: {}", plugin_name, capability)
            return False
        allowed = self._per_plugin.get(plugin_name)
        if allowed is not None and capability not in allowed:
            logger.warning("[sandbox] {} not allowed: {}", plugin_name, capability)
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_deny": list(self._global_deny),
            "per_plugin": {k: list(v) for k, v in self._per_plugin.items()},
        }


plugin_sandbox = PluginSandbox()
