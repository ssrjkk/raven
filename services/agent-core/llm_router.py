from __future__ import annotations

from typing import Any

from loguru import logger


class LLMRouter:
    def __init__(self):
        self._providers: dict[str, Any] = {}

    def register_provider(self, name: str, provider: Any):
        self._providers[name] = provider

    async def complete(self, messages: list[dict], model: str = "default") -> str:
        return "[agent-core] LLM routing placeholder"
