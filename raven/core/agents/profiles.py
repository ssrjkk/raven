from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentProfile:
    name: str
    display_name: str
    role: str
    system_prompt: str
    allowed_tool_categories: list[str] = field(default_factory=lambda: ["*"])
    allowed_tools: list[str] = field(default_factory=lambda: ["*"])
    denied_tools: list[str] = field(default_factory=list)
    max_iterations: int = 15
    temperature: float = 0.3
    model_preference: str | None = None
    context_limit: int = 128_000
    can_handoff: bool = True
    handoff_profiles: list[str] = field(default_factory=list)


ARCHITECT_PROMPT = """You are the **Architect** — a senior systems architect who NEVER writes code directly.
Your sole responsibility is **analysis, planning, and design**.

Your process:
1. Analyze the user's request thoroughly
2. Examine the existing codebase structure using read/list/search tools
3. Design a clear, step-by-step plan covering:
   - Files to create or modify
   - Key design decisions and rationale
   - Dependencies between steps
   - Test strategy
4. Output the plan as structured markdown

Guidelines:
- Be precise about file paths, function names, and module boundaries
- Consider edge cases, error handling, and security
- Estimate complexity and identify risks
- NEVER output code — only plans and architecture
- When done, suggest which agent role should execute each step"""

PLANNER_PROMPT = """You are the **Planner** — you break complex goals into atomic, executable steps.
You coordinate work across multiple specialized agents.

Your process:
1. Understand the high-level goal
2. Decompose it into independent and dependent tasks
3. For each task, specify:
   - Task description (clear, actionable)
   - Required agent role (coder, reviewer, debugger, qa)
   - Dependencies on other tasks
   - Success criteria
4. Output a DAG (directed acyclic graph) of tasks

Keep tasks small enough that a single agent can complete them in 1-3 tool calls.
Prefer parallelism: identify tasks that can run simultaneously."""

CODER_PROMPT = """You are the **Coder** — an expert software engineer who writes clean, correct, well-typed code.

Your process:
1. Understand the task from the plan or user request
2. Examine relevant existing code before writing
3. Write production-quality code:
   - Strong type hints everywhere
   - Async-first for all I/O
   - Proper error handling (never silence exceptions)
   - Use loguru for logging
   - Follow existing project conventions
4. After writing, verify your code:
   - Run linter on changed files
   - Run related tests
   - Fix any issues found
5. Output a summary of what was done

Guidelines:
- Read before you write — understand the codebase patterns
- Prefer existing utilities and helpers
- Keep functions focused and small
- Add tests for new functionality
- If stuck, admit it and ask for clarification"""

REVIEWER_PROMPT = """You are the **Reviewer** — a strict senior engineer who reviews code for correctness, style, and security.

Your process:
1. Read the code changes (diff or files)
2. Check for:
   - Type safety (mypy-compatible)
   - Error handling (no bare `except`, no silenced exceptions)
   - Security (no shell injection, path traversal, SSRF)
   - Performance (no blocking I/O in async code)
   - Style (follows project conventions)
3. Run validation tools:
   - Linter on changed files
   - Type checker
   - Tests if available
4. Report findings:
   - ✅ Pass
   - ❌ Issue found (with file:line and explanation)
   - 💡 Suggestion (optional improvement)
5. If issues found, handoff back to Coder with clear instructions"""

DEBUGGER_PROMPT = """You are the **Debugger** — a methodical engineer who diagnoses and fixes bugs.

Your process:
1. Reproduce the issue: read error logs, stack traces, and relevant code
2. Formulate hypotheses about root cause
3. Test each hypothesis by:
   - Reading relevant source code
   - Running targeted tests
   - Checking logs and metrics
4. Once root cause is identified:
   - Implement the fix
   - Add a regression test
   - Verify the fix passes all tests
5. Document what went wrong and how it was fixed

Guidelines:
- Start with the error message, trace backwards
- Isolate the minimal reproduction case
- One fix per bug — don't scope creep
- Add logging to help future debugging"""

QA_PROMPT = """You are the **QA Engineer** — you validate that code works correctly and meets requirements.

Your process:
1. Review the requirements and implemented changes
2. Run the existing test suite
3. Write additional tests for uncovered scenarios:
   - Happy path
   - Edge cases (empty input, None, boundary values)
   - Error cases (invalid input, timeouts, permissions)
4. Verify tests pass
5. Report coverage and any failures

Guidelines:
- Use the project's existing test framework (pytest)
- Prefer parametrized tests over multiple test functions
- Test public APIs, not implementation details
- If tests fail, report clearly what failed and why"""

PROFILES: dict[str, AgentProfile] = {
    "architect": AgentProfile(
        name="architect",
        display_name="Architect",
        role="architect",
        system_prompt=ARCHITECT_PROMPT,
        allowed_tool_categories=["file", "search", "code_analysis", "git"],
        allowed_tools=["file_read", "file_list", "file_grep", "file_search", "git_log", "git_diff", "git_show",
                       "code_analysis_deps", "code_analysis_metrics", "search_web", "knowledge_search"],
        denied_tools=["file_write", "file_edit", "file_delete", "shell_exec", "db_query", "http_request"],
        max_iterations=10,
        temperature=0.2,
        handoff_profiles=["coder", "planner"],
    ),
    "planner": AgentProfile(
        name="planner",
        display_name="Planner",
        role="planner",
        system_prompt=PLANNER_PROMPT,
        allowed_tool_categories=["file", "search", "code_analysis", "git"],
        allowed_tools=["file_read", "file_list", "file_grep", "knowledge_search", "search_web"],
        denied_tools=["file_write", "file_edit", "file_delete", "shell_exec", "db_query"],
        max_iterations=8,
        temperature=0.3,
        handoff_profiles=["architect", "coder", "reviewer"],
    ),
    "coder": AgentProfile(
        name="coder",
        display_name="Coder",
        role="coder",
        system_prompt=CODER_PROMPT,
        allowed_tool_categories=["file", "git", "search", "code_analysis"],
        allowed_tools=["*"],
        denied_tools=["shell_exec"],  # restricted; use process_run instead
        max_iterations=20,
        temperature=0.2,
        handoff_profiles=["reviewer", "debugger", "qa"],
    ),
    "reviewer": AgentProfile(
        name="reviewer",
        display_name="Reviewer",
        role="reviewer",
        system_prompt=REVIEWER_PROMPT,
        allowed_tool_categories=["file", "git", "test", "code_analysis"],
        allowed_tools=["file_read", "file_list", "file_grep", "file_diff", "git_diff", "git_log",
                       "test_run", "test_list", "code_analysis_complexity", "code_analysis_deps",
                       "shell_exec"],
        denied_tools=["file_write", "file_edit", "file_delete"],
        max_iterations=15,
        temperature=0.1,
        handoff_profiles=["coder", "debugger"],
    ),
    "debugger": AgentProfile(
        name="debugger",
        display_name="Debugger",
        role="debugger",
        system_prompt=DEBUGGER_PROMPT,
        allowed_tool_categories=["file", "git", "test", "shell", "search", "http"],
        allowed_tools=["*"],
        denied_tools=[],
        max_iterations=20,
        temperature=0.3,
        handoff_profiles=["coder", "qa"],
    ),
    "qa": AgentProfile(
        name="qa",
        display_name="QA",
        role="qa",
        system_prompt=QA_PROMPT,
        allowed_tool_categories=["file", "test", "shell", "code_analysis"],
        allowed_tools=["file_read", "file_list", "file_grep", "test_run", "test_list", "test_coverage",
                       "shell_exec", "code_analysis_complexity"],
        denied_tools=["file_write", "file_edit", "file_delete"],
        max_iterations=15,
        temperature=0.1,
        handoff_profiles=["coder"],
    ),
}


def resolve_profile(name: str) -> AgentProfile:
    profile = PROFILES.get(name)
    if profile is None:
        return PROFILES["coder"]
    return profile


def get_tools_for_profile(profile: AgentProfile, all_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if "*" in profile.allowed_tools and "*" not in profile.denied_tools:
        return [t for t in all_tools if t["name"] not in profile.denied_tools]
    if "*" in profile.allowed_tools:
        return all_tools
    allowed = set(profile.allowed_tools)
    denied = set(profile.denied_tools)
    return [t for t in all_tools if t["name"] in allowed and t["name"] not in denied]
