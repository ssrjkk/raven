from __future__ import annotations

from typing import Any

from ravencode.runtime.code_search import code_search as _code_search_handler

from .bash import bash_exec
from .files import (
    edit_file,
    glob_files,
    grep_files,
    read_file,
    verify_file,
    write_file,
)
from .git_tests import (
    git_add,
    git_commit,
    git_diff,
    git_log,
    git_status,
    run_tests,
)
from .memory import (
    memory_recall,
    memory_remember,
    task_delegate,
    task_parallel,
    think,
)
from .sandbox_policy import _sandbox_policy_handler
from .web import (
    web_fetch,
    web_search,
)
from .wrappers import (
    _canvas_render_handler,
    _cron_cancel_handler,
    _cron_list_handler,
    _cron_schedule_handler,
    _nodes_list_handler,
    _talk_handler,
    anchored_summary_append,
    anchored_summary_clear,
    anchored_summary_read,
    anchored_summary_write,
    auto_commit_tool,
    browser_click,
    browser_close,
    browser_evaluate,
    browser_get_html,
    browser_navigate,
    browser_screenshot,
    browser_type,
    checkpoint_list_tool,
    checkpoint_restore_tool,
    checkpoint_save_tool,
    create_artifact,
    download_skill,
    format_file_tool,
    format_files_tool,
    load_skill,
    lsp_completion_tool,
    lsp_definition_tool,
    lsp_diagnostics_tool,
    lsp_hover_tool,
    lsp_references_tool,
    patch_file_tool,
    question_tool,
    read_image,
    redo_action,
    sandbox_exec_tool,
    set_skill_registry,
    smart_edit_tool,
    todo_clear,
    todo_list,
    todo_update,
    todo_write,
    undo_action,
    undo_changes_tool,
)

# ---------------------------------------------------------------------------
# tool registry
# ---------------------------------------------------------------------------

MODULE_TOOLS: dict[str, dict[str, Any]] = {
    "read": {
        "name": "read",
        "dangerous": False,
        "description": "Read the contents of a file. Returns up to 50,000 characters.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "max_chars": {
                    "type": "integer",
                    "description": "Max chars to return (default 50000)",
                    "default": 50000,
                },
            },
            "required": ["path"],
        },
        "handler": read_file,
    },
    "write": {
        "name": "write",
        "dangerous": True,
        "description": "Write content to a file (overwrites existing). Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
                "content": {"type": "string", "description": "File content to write"},
            },
            "required": ["path", "content"],
        },
        "handler": write_file,
    },
    "edit": {
        "name": "edit",
        "dangerous": True,
        "description": "Edit a file by finding and replacing text. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
                "old_string": {"type": "string", "description": "Text to find (must be unique)"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "preview": {"type": "boolean", "description": "Show diff without applying", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
        "handler": edit_file,
    },
    "verify": {
        "name": "verify",
        "dangerous": False,
        "description": "Syntax/type check a source file after editing (Python: ast+ruff+mypy if available; TS/JS: node --check; JSON: parse). Use after write/edit to confirm validity.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
            },
            "required": ["path"],
        },
        "handler": verify_file,
    },
    "glob": {
        "name": "glob",
        "dangerous": False,
        "description": "Search for files matching a glob pattern. Confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. 'src/**/*.ts')"},
                "path": {"type": "string", "description": "Subdirectory inside workspace", "default": None},
            },
            "required": ["pattern"],
        },
        "handler": glob_files,
    },
    "grep": {
        "name": "grep",
        "dangerous": False,
        "description": "Search file contents for a pattern. Confined to workspace. Set use_regex=true to treat pattern as a regular expression.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text or regex to search for"},
                "include": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": None},
                "path": {"type": "string", "description": "Subdirectory inside workspace", "default": None},
                "use_regex": {"type": "boolean", "description": "Treat pattern as a regex", "default": False},
            },
            "required": ["pattern"],
        },
        "handler": grep_files,
    },
    "bash": {
        "name": "bash",
        "dangerous": True,
        "description": "Execute a shell command from the allowlist. Supports quoted arguments.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
            },
            "required": ["command"],
        },
        "handler": bash_exec,
    },
    "web_search": {
        "name": "web_search",
        "dangerous": False,
        "description": "Search the web for current information (DuckDuckGo).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {"type": "integer", "description": "Number of results (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        "handler": web_search,
    },
    "web_fetch": {
        "name": "web_fetch",
        "dangerous": False,
        "description": "Fetch URL contents. SSRF-guarded against private IP ranges.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
        "handler": web_fetch,
    },
    "think": {
        "name": "think",
        "dangerous": False,
        "description": "Use this tool to reason about the problem before taking action. No external effect.",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string", "description": "Your step-by-step reasoning"},
            },
            "required": ["reasoning"],
        },
        "handler": think,
    },
    "task": {
        "name": "task",
        "dangerous": True,
        "description": "Delegate a sub-task to a new agent (max depth 5). Use for parallel work.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Task description for the sub-agent"},
                "context": {"type": "string", "description": "Optional context to pass", "default": None},
            },
            "required": ["description"],
        },
        "handler": task_delegate,
    },
    "task_parallel": {
        "name": "task_parallel",
        "dangerous": True,
        "description": (
            "Run up to 6 INDEPENDENT sub-tasks concurrently, each on its own sub-agent. "
            "Use when sub-tasks do not depend on each other (e.g. 'analyze module A, "
            "module B, module C'). Results come back labeled per sub-task."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of independent task descriptions",
                },
                "context": {"type": "string", "description": "Optional shared context for all sub-agents", "default": None},
            },
            "required": ["tasks"],
        },
        "handler": task_parallel,
    },
    "git_status": {
        "name": "git_status",
        "dangerous": False,
        "description": "Show git working tree status.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": [],
        },
        "handler": git_status,
    },
    "git_diff": {
        "name": "git_diff",
        "dangerous": False,
        "description": "Show git diff of unstaged changes, or staged changes with staged=true.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
                "staged": {"type": "boolean", "description": "Show staged diff instead", "default": False},
            },
            "required": [],
        },
        "handler": git_diff,
    },
    "run_tests": {
        "name": "run_tests",
        "dangerous": False,
        "description": (
            "Run pytest in the workspace and get a compact summary: pass/fail line "
            "plus failing test ids. Much cheaper than reading raw pytest output via bash."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Subdirectory or test file to run (default: workspace root)",
                    "default": None,
                },
                "extra_args": {
                    "type": "string",
                    "description": "Extra pytest args, e.g. '-k pattern' or 'tests/test_x.py'",
                    "default": None,
                },
            },
            "required": [],
        },
        "handler": run_tests,
    },
    "git_log": {
        "name": "git_log",
        "dangerous": False,
        "description": "Show recent git commit history (one-line format).",
        "parameters": {
            "type": "object",
            "properties": {
                "max_count": {"type": "integer", "description": "Number of commits (default 10)", "default": 10},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": [],
        },
        "handler": git_log,
    },
    "git_commit": {
        "name": "git_commit",
        "dangerous": True,
        "description": "Create a git commit with the given message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": ["message"],
        },
        "handler": git_commit,
    },
    "git_add": {
        "name": "git_add",
        "dangerous": True,
        "description": "Stage files for commit.",
        "parameters": {
            "type": "object",
            "properties": {
                "files": {"type": "string", "description": "Files to stage (space-separated)"},
                "path": {"type": "string", "description": "Git repo path (defaults to cwd)", "default": None},
            },
            "required": ["files"],
        },
        "handler": git_add,
    },
    "read_image": {
        "name": "read_image",
        "dangerous": False,
        "description": "Read an image file (png, jpg, gif, webp, svg) confined to workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to workspace"},
            },
            "required": ["path"],
        },
        "handler": read_image,
    },
    "create_artifact": {
        "name": "create_artifact",
        "dangerous": False,
        "description": (
            "Create an interactive artifact (React component, HTML page, Mermaid diagram or SVG). "
            "Use this instead of dumping large code blocks into the chat."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short artifact title, e.g. 'Login Form'"},
                "artifact_type": {
                    "type": "string",
                    "enum": ["react", "html", "mermaid", "svg", "markdown", "python", "typescript"],
                    "description": "Content type for frontend rendering",
                },
                "content": {"type": "string", "description": "Full source code or artifact content"},
                "path": {
                    "type": "string",
                    "description": "Optional workspace-relative path to persist the artifact as a file",
                },
            },
            "required": ["title", "artifact_type", "content"],
        },
        "handler": create_artifact,
    },
    "undo": {
        "name": "undo",
        "dangerous": True,
        "description": "Undo the last file write or edit operation.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": undo_action,
    },
    "redo": {
        "name": "redo",
        "dangerous": True,
        "description": "Redo the last undone file operation.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": redo_action,
    },
    "checkpoint_save": {
        "name": "checkpoint_save",
        "dangerous": False,
        "description": "Save a snapshot of the workspace as a restore point.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Optional description", "default": ""},
            },
            "required": [],
        },
        "handler": checkpoint_save_tool,
    },
    "checkpoint_restore": {
        "name": "checkpoint_restore",
        "dangerous": True,
        "description": "Restore workspace files from a saved checkpoint.",
        "parameters": {
            "type": "object",
            "properties": {
                "cid": {"type": "string", "description": "Checkpoint ID"},
            },
            "required": ["cid"],
        },
        "handler": checkpoint_restore_tool,
    },
    "checkpoint_list": {
        "name": "checkpoint_list",
        "dangerous": False,
        "description": "List all saved checkpoints.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": checkpoint_list_tool,
    },
    "undo_changes": {
        "name": "undo_changes",
        "dangerous": True,
        "description": (
            "Revert all workspace files to the most recent checkpoint. Use when "
            "your edits made things worse and you want a clean slate for this session."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": undo_changes_tool,
    },
    "lsp_completion": {
        "name": "lsp_completion",
        "dangerous": False,
        "description": "Get code completion suggestions via LSP at a given file position.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_completion_tool,
    },
    "lsp_definition": {
        "name": "lsp_definition",
        "dangerous": False,
        "description": "Find definition location of a symbol via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_definition_tool,
    },
    "lsp_references": {
        "name": "lsp_references",
        "dangerous": False,
        "description": "Find all references to a symbol via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_references_tool,
    },
    "lsp_hover": {
        "name": "lsp_hover",
        "dangerous": False,
        "description": "Get type info and documentation for a symbol via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "line": {"type": "integer", "description": "Line number (0-based)"},
                "col": {"type": "integer", "description": "Column (0-based)"},
            },
            "required": ["path", "line", "col"],
        },
        "handler": lsp_hover_tool,
    },
    "lsp_diagnostics": {
        "name": "lsp_diagnostics",
        "dangerous": False,
        "description": "Get compiler/type-checker diagnostics (errors and warnings) for a file via LSP.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["path"],
        },
        "handler": lsp_diagnostics_tool,
    },
    "sandbox_exec": {
        "name": "sandbox_exec",
        "dangerous": True,
        "description": "Execute code in a Docker sandbox (isolated environment). Language: python|javascript|bash.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {
                    "type": "string",
                    "description": "Language (python, javascript, bash)",
                    "default": "python",
                },
            },
            "required": ["code"],
        },
        "handler": sandbox_exec_tool,
    },
    "smart_edit": {
        "name": "smart_edit",
        "dangerous": True,
        "description": (
            "Edit a file using smart modes: old_text+new_text (replace), "
            "insert_after/new_text+insert_before, or append."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_text": {"type": "string", "description": "Text to replace (exact match)", "default": None},
                "new_text": {"type": "string", "description": "Replacement text", "default": None},
                "insert_after": {"type": "string", "description": "Insert new_text after this string", "default": None},
                "insert_before": {
                    "type": "string",
                    "description": "Insert new_text before this string",
                    "default": None,
                },
                "append": {"type": "boolean", "description": "Append new_text to file", "default": False},
            },
            "required": ["path"],
        },
        "handler": smart_edit_tool,
    },
    "patch": {
        "name": "patch",
        "dangerous": True,
        "description": "Apply a unified diff/patch to a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to patch"},
                "diff_text": {"type": "string", "description": "Unified diff text"},
            },
            "required": ["path", "diff_text"],
        },
        "handler": patch_file_tool,
    },
    "format_file": {
        "name": "format_file",
        "dangerous": True,
        "description": "Auto-format a file using the appropriate formatter (ruff for .py, prettier for .ts/.js, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to format"},
            },
            "required": ["path"],
        },
        "handler": format_file_tool,
    },
    "format_files": {
        "name": "format_files",
        "dangerous": True,
        "description": "Auto-format multiple files.",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "File paths to format"},
            },
            "required": ["paths"],
        },
        "handler": format_files_tool,
    },
    "auto_commit": {
        "name": "auto_commit",
        "dangerous": True,
        "description": "Automatically stage all changes and create a smart commit message.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Optional custom commit message", "default": None},
                "path": {"type": "string", "description": "Git repo path", "default": None},
            },
            "required": [],
        },
        "handler": auto_commit_tool,
    },
    "skill": {
        "name": "skill",
        "dangerous": True,
        "description": (
            "Load a SKILL.md file for reusable instructions. Skills are discovered from "
            ".opencode/skills/, ~/.config/opencode/skills/, .claude/skills/, or .agents/skills/."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the skill to load (without .md)"},
            },
            "required": ["name"],
        },
        "handler": load_skill,
    },
    "download_skill": {
        "name": "download_skill",
        "dangerous": True,
        "description": "Download a skill from the remote skill registry (ClawHub-like). Requires set_skill_registry first.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill ID to download"},
            },
            "required": ["name"],
        },
        "handler": download_skill,
    },
    "set_skill_registry": {
        "name": "set_skill_registry",
        "dangerous": True,
        "description": "Set the URL for the remote skill registry to download skills from.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Registry base URL (e.g. https://registry.example.com)"},
            },
            "required": ["url"],
        },
        "handler": set_skill_registry,
    },
    "todowrite": {
        "name": "todowrite",
        "dangerous": False,
        "description": "Create or update tasks in a structured todo list. Each task needs content and optional id/status.",
        "parameters": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": (
                        "List of task dicts with content, optional id (defaults to incremental), "
                        "and optional status (pending/in_progress/completed/cancelled)"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Task description"},
                            "id": {"type": "string", "description": "Optional task ID"},
                            "status": {
                                "type": "string",
                                "description": "Status: pending, in_progress, completed, cancelled",
                                "default": "pending",
                            },
                        },
                        "required": ["content"],
                    },
                },
            },
            "required": ["tasks"],
        },
        "handler": todo_write,
    },
    "todolist": {
        "name": "todolist",
        "dangerous": False,
        "description": "Show the todo list, optionally filtered by status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status: pending, in_progress, completed, cancelled",
                    "default": None,
                },
            },
            "required": [],
        },
        "handler": todo_list,
    },
    "todoupdate": {
        "name": "todoupdate",
        "dangerous": False,
        "description": "Update the status of a todo item.",
        "parameters": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "Task ID to update"},
                "status": {"type": "string", "description": "New status: pending, in_progress, completed, cancelled"},
            },
            "required": ["tid", "status"],
        },
        "handler": todo_update,
    },
    "todoclear": {
        "name": "todoclear",
        "dangerous": False,
        "description": "Clear all todo items.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": todo_clear,
    },
    "question": {
        "name": "question",
        "dangerous": False,
        "description": (
            "Ask the user a question with optional multiple-choice options. "
            "Use when you need clarification, preferences, or decisions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask the user"},
                "header": {"type": "string", "description": "Short header (max 30 chars)", "default": ""},
                "options": {
                    "type": "array",
                    "description": "Optional multiple-choice options",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Display text (1-5 words)"},
                            "description": {"type": "string", "description": "Explanation of choice"},
                        },
                        "required": ["label", "description"],
                    },
                    "default": [],
                },
                "multiple": {"type": "boolean", "description": "Allow selecting multiple choices", "default": False},
            },
            "required": ["question"],
        },
        "handler": question_tool,
    },
    "anchored_summary_read": {
        "name": "anchored_summary_read",
        "dangerous": False,
        "description": (
            "Read the current anchored summary. The summary persists across "
            "conversations and tracks progress, decisions, and context."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": anchored_summary_read,
    },
    "anchored_summary_write": {
        "name": "anchored_summary_write",
        "dangerous": False,
        "description": "Replace the entire anchored summary with new text. Use this to set or reset the persistent session note.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "New anchored summary text"},
            },
            "required": ["text"],
        },
        "handler": anchored_summary_write,
    },
    "anchored_summary_append": {
        "name": "anchored_summary_append",
        "dangerous": False,
        "description": "Append text to the existing anchored summary. Use this to log progress, decisions, or completed items.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to append"},
            },
            "required": ["text"],
        },
        "handler": anchored_summary_append,
    },
    "anchored_summary_clear": {
        "name": "anchored_summary_clear",
        "dangerous": False,
        "description": "Clear the anchored summary.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": anchored_summary_clear,
    },
    "browser_navigate": {
        "name": "browser_navigate",
        "dangerous": True,
        "description": "Navigate a browser to a URL using Playwright.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
        "handler": browser_navigate,
    },
    "browser_click": {
        "name": "browser_click",
        "dangerous": True,
        "description": "Click an element on the page using a CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector to click"},
            },
            "required": ["selector"],
        },
        "handler": browser_click,
    },
    "browser_type": {
        "name": "browser_type",
        "dangerous": True,
        "description": "Type text into an element on the page.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector for the input element"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
        "handler": browser_type,
    },
    "browser_screenshot": {
        "name": "browser_screenshot",
        "dangerous": False,
        "description": "Take a screenshot of the current page.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to save screenshot", "default": "screenshot.png"},
            },
            "required": [],
        },
        "handler": browser_screenshot,
    },
    "browser_get_html": {
        "name": "browser_get_html",
        "dangerous": False,
        "description": "Get the inner HTML of an element (default: body).",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector", "default": "body"},
            },
            "required": [],
        },
        "handler": browser_get_html,
    },
    "browser_evaluate": {
        "name": "browser_evaluate",
        "dangerous": True,
        "description": "Run JavaScript in the browser page and return the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "JavaScript code to evaluate"},
            },
            "required": ["script"],
        },
        "handler": browser_evaluate,
    },
    "browser_close": {
        "name": "browser_close",
        "dangerous": False,
        "description": "Close the browser and release resources.",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": browser_close,
    },
    "canvas_render": {
        "name": "canvas_render",
        "dangerous": True,
        "description": "Render visual components (text, code, table, mermaid, link, image, list, alert) into formatted output",
        "parameters": {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": "List of component dicts with type, content, and optional fields",
                    "items": {"type": "object"},
                },
            },
            "required": ["components"],
        },
        "handler": _canvas_render_handler,
    },
    "nodes_list": {
        "name": "nodes_list",
        "dangerous": False,
        "description": "List all registered execution nodes for distributed task execution",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": _nodes_list_handler,
    },
    "cron_schedule": {
        "name": "cron_schedule",
        "dangerous": True,
        "description": "Schedule a recurring task using a cron expression",
        "parameters": {
            "type": "object",
            "properties": {
                "cron": {"type": "string", "description": "Cron expression (e.g. '0 9 * * *')"},
                "task": {"type": "string", "description": "Task description"},
                "task_id": {"type": "string", "description": "Optional unique task ID"},
            },
            "required": ["cron", "task"],
        },
        "handler": _cron_schedule_handler,
    },
    "cron_list": {
        "name": "cron_list",
        "dangerous": False,
        "description": "List all active scheduled tasks",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "handler": _cron_list_handler,
    },
    "cron_cancel": {
        "name": "cron_cancel",
        "dangerous": True,
        "description": "Cancel a scheduled task by its ID",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to cancel"},
            },
            "required": ["task_id"],
        },
        "handler": _cron_cancel_handler,
    },
    "sandbox_policy": {
        "name": "sandbox_policy",
        "dangerous": True,
        "description": (
            "Show or change the current sandbox security policy. Available: main, "
            "non-main, code-exec, web-browsing, read-only"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "policy": {"type": "string", "description": "Policy name to apply, or omit to show current"},
            },
            "required": [],
        },
        "handler": _sandbox_policy_handler,
    },
    "talk": {
        "name": "talk",
        "dangerous": False,
        "description": "Read text aloud using text-to-speech. Supports system, gtts, edge, elevenlabs providers.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to speak aloud"},
                "voice": {"type": "string", "description": "Voice ID (provider-specific)"},
                "provider": {"type": "string", "description": "TTS provider: system, gtts, edge, elevenlabs"},
            },
            "required": ["text"],
        },
        "handler": _talk_handler,
    },
    "memory_remember": {
        "name": "memory_remember",
        "dangerous": False,
        "description": (
            "Persist a durable fact for future sessions (e.g. user preferences, project "
            "conventions, completed milestones). Duplicates are ignored automatically."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {"type": "string", "description": "The fact to remember, one concise sentence"},
                "key": {"type": "string", "description": "Category key, e.g. notes, milestones, decisions"},
            },
            "required": ["fact"],
        },
        "handler": memory_remember,
    },
    "memory_recall": {
        "name": "memory_recall",
        "dangerous": False,
        "description": "Recall previously persisted facts by category key (default: notes).",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Category key to recall"},
            },
            "required": [],
        },
        "handler": memory_recall,
    },
    "code_search": {
        "name": "code_search",
        "dangerous": False,
        "description": (
            "Search workspace source code with a natural-language query (BM25 over "
            "definition-sized chunks). Best for 'where is X handled?' questions in large "
            "repositories; prefer grep when you know the exact identifier."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query, e.g. 'where retry backoff delay is computed'",
                },
                "k": {"type": "integer", "description": "Maximum number of chunks to return (default 5)"},
            },
            "required": ["query"],
        },
        "handler": _code_search_handler,
    },
}




_PLAN_MODE_DENIED = frozenset({"write", "edit", "bash", "task", "git_commit", "git_add", "checkpoint_restore", "undo_changes", "redo"})
