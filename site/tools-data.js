const TOOLS_DATA = [
    // File Operations
    { name: "read", category: "file", description: "Read file contents with line numbers. Returns up to 50,000 characters.", params: { path: "string", max_chars: "integer" } },
    { name: "write", category: "file", description: "Write content to a file (overwrites existing). Confined to workspace.", params: { path: "string", content: "string" } },
    { name: "edit", category: "file", description: "Find and replace text in a file. Confined to workspace.", params: { path: "string", old_string: "string", new_string: "string" } },
    { name: "verify", category: "file", description: "Syntax/type check a source file (Python: ast+ruff+mypy; TS/JS: node --check; JSON: parse).", params: { path: "string" } },
    { name: "glob", category: "file", description: "Search for files matching a glob pattern. Confined to workspace.", params: { pattern: "string", path: "string" } },
    { name: "grep", category: "file", description: "Search file contents for a pattern. Supports regex.", params: { pattern: "string", include: "string", use_regex: "boolean" } },

    // Shell
    { name: "bash", category: "shell", description: "Execute a shell command from the allowlist. Supports quoted arguments.", params: { command: "string", timeout: "integer" } },

    // Web & Browser
    { name: "web_search", category: "web", description: "Search the web for current information (DuckDuckGo).", params: { query: "string" } },
    { name: "web_fetch", category: "web", description: "Fetch URL contents. SSRF-guarded against private IP ranges.", params: { url: "string" } },
    { name: "browser_navigate", category: "web", description: "Navigate a browser to a URL using Playwright.", params: { url: "string" } },
    { name: "browser_click", category: "web", description: "Click an element on the page using a CSS selector.", params: { selector: "string" } },
    { name: "browser_type", category: "web", description: "Type text into an element on the page.", params: { selector: "string", text: "string" } },
    { name: "browser_screenshot", category: "web", description: "Take a screenshot of the current page.", params: {} },
    { name: "browser_get_html", category: "web", description: "Get the inner HTML of an element (default: body).", params: { selector: "string" } },
    { name: "browser_evaluate", category: "web", description: "Run JavaScript in the browser page and return the result.", params: { script: "string" } },
    { name: "browser_close", category: "web", description: "Close the browser and release resources.", params: {} },

    // Git
    { name: "git_status", category: "git", description: "Show git working tree status.", params: {} },
    { name: "git_diff", category: "git", description: "Show git diff of unstaged or staged changes.", params: { staged: "boolean" } },
    { name: "git_log", category: "git", description: "Show recent git commit history (one-line format).", params: { count: "integer" } },
    { name: "git_commit", category: "git", description: "Create a git commit with the given message.", params: { message: "string" } },
    { name: "git_add", category: "git", description: "Stage files for commit.", params: { files: "array" } },

    // Code & LSP
    { name: "run_tests", category: "code", description: "Run pytest in the workspace and get a compact summary.", params: { path: "string" } },
    { name: "format_file", category: "code", description: "Auto-format a file (ruff for .py, prettier for .js/.ts/.json).", params: { path: "string" } },
    { name: "format_files", category: "code", description: "Auto-format multiple files at once.", params: { paths: "array" } },
    { name: "smart_edit", category: "code", description: "Edit a file using smart modes: replace, insert_after, insert_before, append.", params: { path: "string", mode: "string" } },
    { name: "patch", category: "code", description: "Apply a unified diff/patch to a file.", params: { path: "string", diff: "string" } },
    { name: "lsp_completion", category: "code", description: "Get code completion suggestions via LSP at a given position.", params: { path: "string", line: "integer", character: "integer" } },
    { name: "lsp_definition", category: "code", description: "Find definition location of a symbol via LSP.", params: { path: "string", symbol: "string" } },
    { name: "lsp_references", category: "code", description: "Find all references to a symbol via LSP.", params: { path: "string", symbol: "string" } },
    { name: "lsp_hover", category: "code", description: "Get type info and documentation for a symbol via LSP.", params: { path: "string", symbol: "string" } },
    { name: "lsp_diagnostics", category: "code", description: "Get compiler/type-checker diagnostics (errors and warnings) via LSP.", params: { path: "string" } },
    { name: "code_search", category: "code", description: "Search workspace source code with a natural-language query (BM25).", params: { query: "string" } },

    // Agent & Memory
    { name: "think", category: "agent", description: "Reason about the problem before taking action. No external effects.", params: { thought: "string" } },
    { name: "task", category: "agent", description: "Delegate a sub-task to a new agent (max depth 5). Use for parallel work.", params: { description: "string" } },
    { name: "task_parallel", category: "agent", description: "Run up to 6 independent sub-tasks concurrently on separate sub-agents.", params: { tasks: "array" } },
    { name: "memory_remember", category: "agent", description: "Persist a durable fact for future sessions (user preferences, project conventions).", params: { key: "string", value: "string" } },
    { name: "memory_recall", category: "agent", description: "Recall previously persisted facts by category key.", params: { key: "string" } },
    { name: "question", category: "agent", description: "Ask the user a question with optional multiple-choice options.", params: { question: "string", options: "array" } },

    // Workflow
    { name: "undo", category: "workflow", description: "Undo the last file write or edit operation.", params: {} },
    { name: "redo", category: "workflow", description: "Redo the last undone file operation.", params: {} },
    { name: "checkpoint_save", category: "workflow", description: "Save a snapshot of the workspace as a restore point.", params: { name: "string" } },
    { name: "checkpoint_restore", category: "workflow", description: "Restore workspace files from a saved checkpoint.", params: { name: "string" } },
    { name: "checkpoint_list", category: "workflow", description: "List all saved checkpoints.", params: {} },
    { name: "undo_changes", category: "workflow", description: "Revert all workspace files to the most recent checkpoint.", params: {} },
    { name: "auto_commit", category: "workflow", description: "Automatically stage all changes and create a smart commit message.", params: {} },
    { name: "todowrite", category: "workflow", description: "Create or update tasks in a structured todo list.", params: { content: "string", status: "string" } },
    { name: "todolist", category: "workflow", description: "Show the todo list, optionally filtered by status.", params: { status: "string" } },
    { name: "todoupdate", category: "workflow", description: "Update the status of a todo item.", params: { id: "integer", status: "string" } },
    { name: "todoclear", category: "workflow", description: "Clear all todo items.", params: {} },
    { name: "anchored_summary_write", category: "workflow", description: "Replace the entire anchored summary with new text.", params: { text: "string" } },
    { name: "anchored_summary_append", category: "workflow", description: "Append text to the existing anchored summary.", params: { text: "string" } },
    { name: "anchored_summary_read", category: "workflow", description: "Read the current anchored summary.", params: {} },
    { name: "anchored_summary_clear", category: "workflow", description: "Clear the anchored summary.", params: {} },

    // Infrastructure
    { name: "sandbox_exec", category: "infra", description: "Execute code in a Docker sandbox (isolated environment).", params: { code: "string", language: "string" } },
    { name: "sandbox_policy", category: "infra", description: "Show or change the current sandbox security policy.", params: { action: "string" } },
    { name: "create_artifact", category: "infra", description: "Create an interactive artifact (React component, HTML page, Mermaid diagram, SVG).", params: { type: "string", content: "string" } },
    { name: "read_image", category: "infra", description: "Read an image file (png, jpg, gif, webp, svg). Confined to workspace.", params: { path: "string" } },
    { name: "canvas_render", category: "infra", description: "Render visual components (text, code, table, mermaid, link, image, list, alert).", params: { type: "string", content: "string" } },
    { name: "nodes_list", category: "infra", description: "List all registered execution nodes for distributed task execution.", params: {} },
    { name: "cron_schedule", category: "infra", description: "Schedule a recurring task using a cron expression.", params: { schedule: "string", task: "string" } },
    { name: "cron_list", category: "infra", description: "List all active scheduled tasks.", params: {} },
    { name: "cron_cancel", category: "infra", description: "Cancel a scheduled task by its ID.", params: { id: "string" } },
    { name: "talk", category: "infra", description: "Read text aloud using text-to-speech. Supports system, gtts, edge, elevenlabs.", params: { text: "string", provider: "string" } },
    { name: "skill", category: "infra", description: "Load a SKILL.md file for reusable instructions.", params: { name: "string" } },
    { name: "download_skill", category: "infra", description: "Download a skill from the remote skill registry.", params: { name: "string" } },
    { name: "set_skill_registry", category: "infra", description: "Set the URL for the remote skill registry to download skills from.", params: { url: "string" } },
];
