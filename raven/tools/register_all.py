from __future__ import annotations

from typing import Any

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.ab_testing import register_ab_testing_tools
from raven.tools.analytics import register_analytics_tools
from raven.tools.browser import register_browser_tools
from raven.tools.canvas import register_canvas_tools
from raven.tools.chaos import register_chaos_tools
from raven.tools.ci import register_ci_tools
from raven.tools.code_analysis import register_code_analysis_tools
from raven.tools.collaboration import register_collaboration_tools
from raven.tools.cost_management import register_cost_management_tools
from raven.tools.db import register_db_tools
from raven.tools.delegation import register_delegation_tools
from raven.tools.dreaming import register_dreaming_tools
from raven.tools.email import register_email_tools
from raven.tools.env import register_env_tools
from raven.tools.file import register_file_tools
from raven.tools.finetune import register_finetune_tools
from raven.tools.git import register_git_tools
from raven.tools.github import register_github_tools
from raven.tools.http import register_http_tools
from raven.tools.knowledge import register_knowledge_tools
from raven.tools.mcp_tools import register_mcp_tools
from raven.tools.media import register_media_tools
from raven.tools.nodes import register_nodes_tools
from raven.tools.notify import register_notify_tools
from raven.tools.plugin import register_plugin_tools
from raven.tools.process import register_process_tools
from raven.tools.rag import register_rag_tools
from raven.tools.reverse_engineering import register_re_tools
from raven.tools.shell import register_shell_tools
from raven.tools.tests import register_test_tools
from raven.tools.utils import register_util_tools
from raven.tools.voice import register_voice_tools
from raven.tools.web_search import register_web_search_tools as register_search_tools
from raven.tools.workflow import register_workflow_tools


def register_all_tools(registry: ToolRegistry) -> ToolRegistry:
    register_http_tools(registry)
    register_knowledge_tools(registry)
    register_media_tools(registry)
    register_file_tools(registry)
    register_shell_tools(registry)
    register_browser_tools(registry)
    register_canvas_tools(registry)
    register_nodes_tools(registry)
    register_util_tools(registry)
    register_process_tools(registry)
    register_notify_tools(registry)
    register_db_tools(registry)
    register_env_tools(registry)
    register_git_tools(registry)
    register_search_tools(registry)
    register_ci_tools(registry)
    register_test_tools(registry)
    register_voice_tools(registry)
    register_collaboration_tools(registry)
    register_rag_tools(registry)
    register_finetune_tools(registry)
    register_chaos_tools(registry)
    register_email_tools(registry)
    register_analytics_tools(registry)
    register_ab_testing_tools(registry)
    register_code_analysis_tools(registry)
    register_cost_management_tools(registry)
    register_delegation_tools(registry)
    register_dreaming_tools(registry)
    register_github_tools(registry)
    register_plugin_tools(registry)
    register_workflow_tools(registry)
    register_re_tools(registry)
    return registry


def create_tool_registry(mcp_pool: Any = None) -> ToolRegistry:
    registry = ToolRegistry()
    register_all_tools(registry)
    if mcp_pool is not None:
        register_mcp_tools(registry, mcp_pool)
    return registry


_TASK_EXEC_TOKENS: tuple[str, ...] = (
    "shell",
    "python",
    "process_",
    "browser_",
    "mcp_",
    "node_",
    "chaos_",
    "db_query",
    "email_send",
    "http_post",
    "git_commit",
    "git_push",
    "git_pull",
    "git_checkout",
    "git_create_pr",
    "git_review",
    "plugin_",
)


def create_task_tool_registry(mcp_pool: Any = None) -> ToolRegistry:
    """Registry for planner-driven task execution (web / Telegram / gateway /task).

    Excludes exec-class, exfiltration-capable and destructive tools so a
    planner-authored step cannot escalate to arbitrary command execution.
    """
    registry = create_tool_registry(mcp_pool)
    for name in [t.name for t in registry.list() if any(tok in t.name for tok in _TASK_EXEC_TOKENS)]:
        registry.unregister(name)
    return registry
