from __future__ import annotations

from enum import Enum

from loguru import logger


class Capability(str, Enum):
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

    def deny_global(self, *capabilities: str):
        self._global_deny.update(capabilities)

    def allow_plugin(self, plugin_name: str, *capabilities: str):
        if plugin_name not in self._per_plugin:
            self._per_plugin[plugin_name] = set()
        self._per_plugin[plugin_name].update(capabilities)

    def deny_plugin(self, plugin_name: str, *capabilities: str):
        if plugin_name in self._per_plugin:
            for cap in capabilities:
                self._per_plugin[plugin_name].discard(cap)

    def check(self, plugin_name: str, capability: str) -> bool:
        if capability in self._global_deny:
            logger.warning("[sandbox] {} blocked by global deny: {}", plugin_name, capability)
            return False
        allowed = self._per_plugin.get(plugin_name)
        if allowed is not None and capability not in allowed:
            logger.warning("[sandbox] {} not allowed: {}", plugin_name, capability)
            return False
        return True

    def permitted(self, plugin_name: str) -> list[str]:
        allowed = self._per_plugin.get(plugin_name)
        if allowed is None:
            return [c.value for c in Capability]
        return list(allowed)

    def to_dict(self) -> dict:
        return {
            "global_deny": list(self._global_deny),
            "per_plugin": {k: list(v) for k, v in self._per_plugin.items()},
        }


plugin_sandbox = PluginSandbox()
