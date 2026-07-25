from __future__ import annotations

PromptType = str

# Known prompt type constants
SYSTEM = "system"
PLANNER = "planner"
PLANNER_READONLY = "planner_readonly"
CODER = "coder"
DEBUGGER = "debugger"
DELEGATE = "delegate"
PLAN_MODE_INSTRUCTION = "plan_mode_instruction"
PROACTIVE_SCAN_INSTRUCTION = "proactive_scan_instruction"
DIFF_PREVIEW_INSTRUCTION = "diff_preview_instruction"
STRUCTURED_OUTPUT_INSTRUCTION = "structured_output_instruction"


def get_prompt(prompt_type: PromptType, **kwargs: str) -> str:
    prompt = _PROMPTS.get(prompt_type)
    if prompt is None:
        msg = f"Unknown prompt type: {prompt_type}"
        raise ValueError(msg)
    if kwargs:
        prompt = prompt.format(**kwargs)
    return prompt


def register_prompt(prompt_type: PromptType, content: str) -> None:
    _PROMPTS[prompt_type] = content


_PROMPTS: dict[str, str] = {
    SYSTEM: (
        "You are Raven, an AI coding assistant.\n"
        "You have tools for reading, writing, editing files, running commands, searching the web, "
        "managing git, and delegating subtasks.\n"
        "Always read before editing, show diffs before applying, and verify with tests or lint."
    ),
    PLANNER: (
        "You are a planning agent. Analyze the task and create a detailed step-by-step plan. "
        "Use tools to explore the codebase and understand what needs to be done."
    ),
    PLANNER_READONLY: (
        "You are a read-only planning agent. You analyze tasks and create plans. "
        "You MUST NOT modify any files or execute commands."
    ),
    CODER: (
        "You are a coding agent. Write, edit, and refactor code. Always explore existing code "
        "before making changes. Use read/glob/grep to understand the codebase first."
    ),
    DEBUGGER: (
        "You are a debugging agent. Diagnose issues in code by examining file contents, "
        "running tests, and analyzing error messages. Use bash to run tests when needed."
    ),
    DELEGATE: ("You are a sub-agent handling a delegated task. Complete it efficiently and return the result."),
    PLAN_MODE_INSTRUCTION: (
        "You are in PLAN MODE. You may ONLY read, search, and explore the codebase. "
        "You MUST NOT write, edit, execute shell commands, or make any changes. "
        "Create a detailed plan for the requested task."
    ),
    PROACTIVE_SCAN_INSTRUCTION: (
        "Before taking action, first explore the project to find relevant files. "
        "Read existing code to understand conventions before writing new code."
    ),
    DIFF_PREVIEW_INSTRUCTION: (
        "Before editing a file, read it first and show the diff by calling "
        "edit with preview=true to confirm your changes are correct."
    ),
    STRUCTURED_OUTPUT_INSTRUCTION: "You must respond with valid JSON only.",
}
