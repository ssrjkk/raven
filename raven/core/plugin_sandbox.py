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
        self._network_allow: dict[str, list[str]] = {}
        self._network_deny: dict[str, list[str]] = {}

    def check(self, plugin_name: str, capability: str) -> bool:
        if capability in self._global_deny:
            logger.warning("[sandbox] {} blocked by global deny: {}", plugin_name, capability)
            return False
        allowed = self._per_plugin.get(plugin_name)
        if allowed is not None and capability not in allowed:
            logger.warning("[sandbox] {} not allowed: {}", plugin_name, capability)
            return False
        return True

    def check_network(self, plugin_name: str, domain: str) -> bool:
        allow = self._network_allow.get(plugin_name)
        deny = self._network_deny.get(plugin_name)
        if deny and domain in deny:
            return False
        if allow and domain not in allow:
            return False
        if not allow and not deny:
            return self.check(plugin_name, Capability.NETWORK)
        return True

    def set_network_rules(self, plugin_name: str, allow: list[str] | None = None, deny: list[str] | None = None):
        if allow is not None:
            self._network_allow[plugin_name] = allow
        if deny is not None:
            self._network_deny[plugin_name] = deny

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_deny": list(self._global_deny),
            "per_plugin": {k: list(v) for k, v in self._per_plugin.items()},
        }


plugin_sandbox = PluginSandbox()
