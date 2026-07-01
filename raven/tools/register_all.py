from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.browser import register_browser_tools
from raven.tools.canvas import register_canvas_tools
from raven.tools.db import register_db_tools
from raven.tools.env import register_env_tools
from raven.tools.file import register_file_tools
from raven.tools.http import register_http_tools
from raven.tools.nodes import register_nodes_tools
from raven.tools.notify import register_notify_tools
from raven.tools.process import register_process_tools
from raven.tools.shell import register_shell_tools
from raven.tools.utils import register_util_tools


def register_all_tools(registry: ToolRegistry) -> ToolRegistry:
    register_http_tools(registry)
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
    return registry


def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_all_tools(registry)
    return registry
