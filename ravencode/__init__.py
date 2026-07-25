"""
ravencode — Autonomous AI engineering framework.

Enables AI agents to autonomously read, write, edit, search, and execute
code across the codebase using a ReAct loop with multi-provider LLM support.
"""

from __future__ import annotations

__author__ = "ssrjkk"

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ravencode.agents.custom_agents import CustomAgentDef
    from ravencode.agents.multi import MultiAgentOrchestrator, SubTask, TaskResult, get_multi_orchestrator
    from ravencode.agents.orchestrator import AgentResult, AgentType, Orchestrator
    from ravencode.api.client import AIOSClient, AIResponse, AIUnavailableError
    from ravencode.api.server import run_openai_server
    from ravencode.cli.main import cli
    from ravencode.cli.tui import tui_run
    from ravencode.config import (
        AgentDef as AgentDefCfg,
    )
    from ravencode.config import (
        ConfigLoader,
        FormatterDef,
        LspServerDef,
        McpServerDef,
        ModelConfig,
        PermissionRuleDef,
        ProviderConfig,
        RavenConfig,
        ThemeColors,
        get_config,
        load_config_file,
    )
    from ravencode.integrations.base import CIProvider, EventContext, EventType
    from ravencode.integrations.github import GitHubIntegration
    from ravencode.integrations.gitlab import GitLabIntegration
    from ravencode.mcp.server import MCPServer, run_mcp_server
    from ravencode.runtime.agent_core import AgentConfig, EventEmitter, ReActAgent
    from ravencode.runtime.autogit import auto_commit
    from ravencode.runtime.cache import ResponseCache, get_cache
    from ravencode.runtime.checkpoints import CheckpointManager, get_checkpoint_manager
    from ravencode.runtime.context import Conversation, MemoryStore
    from ravencode.runtime.diff import apply_patch, compute_patch, smart_edit
    from ravencode.runtime.formatters import format_file, format_files
    from ravencode.runtime.lsp import LSPClient
    from ravencode.runtime.permissions import PermissionManager, PermissionRule
    from ravencode.runtime.plugins import Plugin, PluginRegistry, get_plugin_registry
    from ravencode.runtime.sandbox import Sandbox, get_sandbox
    from ravencode.runtime.session import SessionStore, get_session_store, session_load, session_save
    from ravencode.runtime.shell import ShellExecutor
    from ravencode.runtime.tools import execute_tool, get_tool_definitions
    from ravencode.runtime.undo import UndoManager, get_undo_manager
    from ravencode.runtime.watcher import FileWatcher, get_watcher


def __getattr__(name: str):
    _lazy_map = {
        "AIOSClient": "ravencode.api.client",
        "AIResponse": "ravencode.api.client",
        "AIUnavailableError": "ravencode.api.client",
        "Orchestrator": "ravencode.agents.orchestrator",
        "AgentResult": "ravencode.agents.orchestrator",
        "AgentType": "ravencode.agents.orchestrator",
        "CustomAgentDef": "ravencode.agents.custom_agents",
        "MultiAgentOrchestrator": "ravencode.agents.multi",
        "SubTask": "ravencode.agents.multi",
        "TaskResult": "ravencode.agents.multi",
        "get_multi_orchestrator": "ravencode.agents.multi",
        "AgentConfig": "ravencode.runtime.agent_core",
        "ReActAgent": "ravencode.runtime.agent_core",
        "EventEmitter": "ravencode.runtime.agent_core",
        "Conversation": "ravencode.runtime.context",
        "MemoryStore": "ravencode.runtime.context",
        "ShellExecutor": "ravencode.runtime.shell",
        "execute_tool": "ravencode.runtime.tools",
        "get_tool_definitions": "ravencode.runtime.tools",
        "UndoManager": "ravencode.runtime.undo",
        "get_undo_manager": "ravencode.runtime.undo",
        "PermissionManager": "ravencode.runtime.permissions",
        "PermissionRule": "ravencode.runtime.permissions",
        "Plugin": "ravencode.runtime.plugins",
        "PluginRegistry": "ravencode.runtime.plugins",
        "get_plugin_registry": "ravencode.runtime.plugins",
        "ResponseCache": "ravencode.runtime.cache",
        "get_cache": "ravencode.runtime.cache",
        "LSPClient": "ravencode.runtime.lsp",
        "CheckpointManager": "ravencode.runtime.checkpoints",
        "get_checkpoint_manager": "ravencode.runtime.checkpoints",
        "FileWatcher": "ravencode.runtime.watcher",
        "get_watcher": "ravencode.runtime.watcher",
        "MCPServer": "ravencode.mcp.server",
        "run_mcp_server": "ravencode.mcp.server",
        "cli": "ravencode.cli.main",
        "tui_run": "ravencode.cli.tui",
        "RavenConfig": "ravencode.config.loader",
        "ConfigLoader": "ravencode.config.loader",
        "get_config": "ravencode.config.loader",
        "load_config_file": "ravencode.config.loader",
        "ProviderConfig": "ravencode.config.models",
        "ModelConfig": "ravencode.config.models",
        "PermissionRuleDef": "ravencode.config.models",
        "AgentDefCfg": "ravencode.config.models:AgentDef",
        "McpServerDef": "ravencode.config.models",
        "LspServerDef": "ravencode.config.models",
        "FormatterDef": "ravencode.config.models",
        "ThemeColors": "ravencode.config.models",
        "CIProvider": "ravencode.integrations.base",
        "EventContext": "ravencode.integrations.models",
        "EventType": "ravencode.integrations.models",
        "GitHubIntegration": "ravencode.integrations.github",
        "GitLabIntegration": "ravencode.integrations.gitlab",
        "Sandbox": "ravencode.runtime.sandbox",
        "get_sandbox": "ravencode.runtime.sandbox",
        "smart_edit": "ravencode.runtime.diff",
        "apply_patch": "ravencode.runtime.diff",
        "compute_patch": "ravencode.runtime.diff",
        "format_file": "ravencode.runtime.formatters",
        "format_files": "ravencode.runtime.formatters",
        "auto_commit": "ravencode.runtime.autogit",
        "SessionStore": "ravencode.runtime.session",
        "get_session_store": "ravencode.runtime.session",
        "session_save": "ravencode.runtime.session",
        "session_load": "ravencode.runtime.session",
        "run_openai_server": "ravencode.api.server",
    }
    entry = _lazy_map.get(name)
    if entry is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    if ":" in entry:
        module_path, attr_name = entry.split(":", 1)
    else:
        module_path = entry
        attr_name = name
    mod = importlib.import_module(module_path)
    attr = getattr(mod, attr_name)
    globals()[name] = attr
    return attr


__all__ = [
    "AIOSClient",
    "AIResponse",
    "AIUnavailableError",
    "AgentConfig",
    "AgentDefCfg",
    "AgentResult",
    "AgentType",
    "CIProvider",
    "CheckpointManager",
    "ConfigLoader",
    "Conversation",
    "CustomAgentDef",
    "EventContext",
    "EventEmitter",
    "EventType",
    "FileWatcher",
    "FormatterDef",
    "GitHubIntegration",
    "GitLabIntegration",
    "LSPClient",
    "LspServerDef",
    "MCPServer",
    "McpServerDef",
    "MemoryStore",
    "ModelConfig",
    "MultiAgentOrchestrator",
    "Orchestrator",
    "PermissionManager",
    "PermissionRule",
    "PermissionRuleDef",
    "Plugin",
    "PluginRegistry",
    "ProviderConfig",
    "RavenConfig",
    "ReActAgent",
    "ResponseCache",
    "Sandbox",
    "SessionStore",
    "ShellExecutor",
    "SubTask",
    "TaskResult",
    "ThemeColors",
    "UndoManager",
    "apply_patch",
    "auto_commit",
    "cli",
    "compute_patch",
    "execute_tool",
    "format_file",
    "format_files",
    "get_cache",
    "get_checkpoint_manager",
    "get_config",
    "get_multi_orchestrator",
    "get_plugin_registry",
    "get_sandbox",
    "get_session_store",
    "get_tool_definitions",
    "get_undo_manager",
    "get_watcher",
    "load_config_file",
    "run_mcp_server",
    "run_openai_server",
    "session_load",
    "session_save",
    "smart_edit",
    "tui_run",
]
