"""Raven core engine.

The names below are re-exported for convenience and resolved on first attribute access: an eager
barrel here meant that `import raven` — and therefore every `import raven.<anything>`, including
the plugin worker's and the coding agent's — pulled the gateway, every LLM provider and the
database before running a line of the caller's code.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__author__ = "ssrjkk"

if TYPE_CHECKING:
    from raven.core.agent.agent import Agent, AgentConfig
    from raven.core.agent.registry import AgentRegistry
    from raven.core.config import Settings, settings
    from raven.core.db import Database
    from raven.core.gateway.gateway import Gateway
    from raven.core.llm import (
        AnthropicProvider,
        LLMProvider,
        LLMResponse,
        LLMRouter,
        OllamaProvider,
        OpenAIProvider,
        OpenRouterProvider,
        ToolCall,
    )
    from raven.core.models import IncomingMessage, Message, PluginTool, Session
    from raven.core.plugin_loader import PluginLoader
    from raven.core.version import __version__


_LAZY_MAP = {
    "Agent": "raven.core.agent.agent",
    "AgentConfig": "raven.core.agent.agent",
    "AgentRegistry": "raven.core.agent.registry",
    "AnthropicProvider": "raven.core.llm",
    "Database": "raven.core.db",
    "Gateway": "raven.core.gateway.gateway",
    "IncomingMessage": "raven.core.models",
    "LLMProvider": "raven.core.llm",
    "LLMResponse": "raven.core.llm",
    "LLMRouter": "raven.core.llm",
    "Message": "raven.core.models",
    "OllamaProvider": "raven.core.llm",
    "OpenAIProvider": "raven.core.llm",
    "OpenRouterProvider": "raven.core.llm",
    "PluginLoader": "raven.core.plugin_loader",
    "PluginTool": "raven.core.models",
    "Session": "raven.core.models",
    "Settings": "raven.core.config",
    "ToolCall": "raven.core.llm",
    "__version__": "raven.core.version",
    "settings": "raven.core.config",
}


def __getattr__(name: str):
    module_path = _LAZY_MAP.get(name)
    if module_path is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    attr = getattr(importlib.import_module(module_path), name)
    globals()[name] = attr
    return attr


__all__ = [
    "Agent",
    "AgentConfig",
    "AgentRegistry",
    "AnthropicProvider",
    "Database",
    "Gateway",
    "IncomingMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMRouter",
    "Message",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "PluginLoader",
    "PluginTool",
    "Session",
    "Settings",
    "ToolCall",
    "__version__",
    "settings",
]
