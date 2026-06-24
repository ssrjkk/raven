"""
ravencode — Autonomous AI engineering framework.

Enables AI agents to autonomously read, write, edit, search, and execute
code across the codebase using a ReAct loop with multi-provider LLM support.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ravencode.agents.orchestrator import AgentResult, AgentType, Orchestrator
    from ravencode.api.client import AIOSClient, AIResponse
    from ravencode.runtime.agent_core import ReActAgent
    from ravencode.runtime.context import Conversation
    from ravencode.runtime.shell import ShellExecutor
    from ravencode.runtime.tools import execute_tool, get_tool_definitions


def __getattr__(name: str):
    _lazy_map = {
        "AIOSClient": "ravencode.api.client",
        "AIResponse": "ravencode.api.client",
        "Orchestrator": "ravencode.agents.orchestrator",
        "AgentResult": "ravencode.agents.orchestrator",
        "AgentType": "ravencode.agents.orchestrator",
        "ReActAgent": "ravencode.runtime.agent_core",
        "Conversation": "ravencode.runtime.context",
        "ShellExecutor": "ravencode.runtime.shell",
        "execute_tool": "ravencode.runtime.tools",
        "get_tool_definitions": "ravencode.runtime.tools",
    }
    module_path = _lazy_map.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(module_path)
    attr = getattr(mod, name)
    globals()[name] = attr
    return attr


__all__ = [
    "AIOSClient",
    "AIResponse",
    "Orchestrator",
    "AgentResult",
    "AgentType",
    "ReActAgent",
    "Conversation",
    "ShellExecutor",
    "execute_tool",
    "get_tool_definitions",
]
