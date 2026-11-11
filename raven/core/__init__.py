"""Core engine namespace.

Every name here is resolved on first attribute access. An eager barrel this wide meant that
`import raven.core.anything` — the plugin worker, the coding agent's tool registry, `raven doctor` —
first had to import the gateway, all eight LLM providers, the database and the agent registry: 9.4 s
measured on the reference machine before the caller ran a single line.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from raven.core.agent.agent import Agent, AgentConfig
    from raven.core.agent.registry import AgentRegistry
    from raven.core.config import Settings, settings
    from raven.core.db import Database
    from raven.core.events import EventBus
    from raven.core.features import FeatureFlags
    from raven.core.gateway.gateway import Gateway
    from raven.core.llm import (
        AnthropicProvider,
        AzureProvider,
        BedrockProvider,
        CopilotProvider,
        LLMProvider,
        LLMResponse,
        LLMRouter,
        OllamaProvider,
        OpenAIProvider,
        OpenRouterProvider,
        ToolCall,
        VertexAIProvider,
    )
    from raven.core.models import IncomingMessage, Message, PluginTool, Session
    from raven.core.plugin_loader import PluginLoader


_LAZY_MAP = {
    "Agent": "raven.core.agent.agent",
    "AgentConfig": "raven.core.agent.agent",
    "AgentRegistry": "raven.core.agent.registry",
    "AnthropicProvider": "raven.core.llm",
    "AzureProvider": "raven.core.llm",
    "BedrockProvider": "raven.core.llm",
    "CopilotProvider": "raven.core.llm",
    "Database": "raven.core.db",
    "EventBus": "raven.core.events",
    "FeatureFlags": "raven.core.features",
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
    "VertexAIProvider": "raven.core.llm",
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
    "AzureProvider",
    "BedrockProvider",
    "CopilotProvider",
    "Database",
    "EventBus",
    "FeatureFlags",
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
    "VertexAIProvider",
    "settings",
]
