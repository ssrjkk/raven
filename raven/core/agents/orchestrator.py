from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from raven.core.agents.profiles import AgentProfile, resolve_profile
from raven.core.agents.router import IntentRouter
from raven.core.agents.validation import validate_tool_arguments
from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.security.context_filter import redact_pii

if TYPE_CHECKING:
    from raven.core.llm import LLMResponse, LLMRouter, ToolCall
    from raven.core.task_engine.tool_registry import ToolRegistry

AgentStatus = Literal["success", "error", "max_steps"]

_VALID_HANDOFF_PROFILES = frozenset(
    {"architect", "planner", "coder", "reviewer", "debugger", "qa", "researcher", "security", "done"}
)

_PATH_KEYS = ("path", "file", "directory", "source", "target")

_IMPLEMENT_TOOLS = frozenset(
    {"file_write", "file_edit", "file_append", "shell", "python", "git_commit", "git_add"}
)


@dataclass
class AgentContext:
    """Explicit execution context threaded through every tool call.

    Replaces reliance on module-level global state: workspace and permissions
    are provided by the caller and flow down to security checks and tools.
    """

    query: str
    workspace: Path | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    started_at: float = field(default_factory=time.monotonic)
    tokens_used: int = 0
    handoff_count: int = 0
    plan_steps: list[str] = field(default_factory=list)
    critic_passes: int = 0


@dataclass
class AgentResult:
    content: str
    profile: str
    iterations: int
    handoffs: int
    duration: float
    tokens_used: int
    status: AgentStatus

    @property
    def success(self) -> bool:
        return self.status == "success"


class StatusEmitter:
    def __init__(self, send_fn: Callable[..., Any] | None = None):
        self._send = send_fn
        self._events: list[dict[str, Any]] = []

    async def emit(self, event_type: str, profile: str, detail: str = "", data: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "type": "agent_status",
            "event": event_type,
            "profile": profile,
            "detail": detail,
            "ts": time.time(),
        }
        if data:
            payload["data"] = data
        self._events.append(payload)
        if self._send:
            try:
                await self._send(json.dumps(payload))
            except Exception as e:
                logger.debug("StatusEmitter send failed: {}", e)

    async def agent_started(self, profile: str, query: str) -> None:
        await self.emit("agent_started", profile, f"{profile} started", {"query": query[:200]})

    async def agent_completed(self, profile: str, summary: str = "") -> None:
        await self.emit("agent_completed", profile, summary)

    async def tool_call(self, profile: str, tool: str, args: dict[str, Any]) -> None:
        await self.emit("tool_call", profile, tool, {"args": args})

    async def tool_result(self, profile: str, tool: str, status: str) -> None:
        await self.emit("tool_result", profile, f"{tool}: {status}")

    async def thinking(self, profile: str, thought: str) -> None:
        await self.emit("thinking", profile, thought[:200])

    async def error(self, profile: str, msg: str) -> None:
        await self.emit("error", profile, msg)

    async def handoff(self, from_profile: str, to_profile: str, reason: str) -> None:
        await self.emit("handoff", to_profile, f"{from_profile} → {to_profile}: {reason}", {"from": from_profile, "to": to_profile})

    async def plan_created(self, profile: str, steps: list[str]) -> None:
        await self.emit("plan_created", profile, f"Plan: {len(steps)} steps", {"steps": steps})

    async def planning(self, profile: str) -> None:
        await self.emit("planning", profile, "Analyzing the request")

    async def critic_started(self, profile: str) -> None:
        await self.emit("critic_started", profile, "Reviewing the result")

    async def step_started(self, profile: str, index: int, total: int, description: str) -> None:
        await self.emit("step_started", profile, description[:200], {"index": index, "total": total})


_PLAN_PROMPT = """Break down the user's request into a concise, ordered list of execution steps (max 8).
Each step must be a single sentence describing one concrete, verifiable action the assistant will take.
Prioritize: understand-first (read/explore before writing), then implement, then verify (lint/tests).
Steps should be atomic and dependency-ordered so they can be executed sequentially without rework.
Do NOT write any code. Return ONLY a valid JSON array of strings, with no commentary.
Example output:
["Explore the project structure", "Implement the auth module", "Run tests"]"""

_CRITIC_PROMPT = """You are the final reviewer of an automated coding agent. Judge whether the assistant's output fully satisfies the user's goal.
Check rigorously: unmet requirements, unverified code, missing tests, obvious bugs, security issues, and whether claims match actual tool results.
The assistant must not claim work it did not do, and must not leave TODO/FIXME or unverified code as "done".
If the goal is fully met, reply EXACTLY with the single word: ACCEPT
Otherwise reply with a short, concrete critique (2-4 sentences) listing the specific issues that must be fixed before delivery.

Rules:
- Prefer ACCEPT only when the evidence shows the goal is genuinely complete.
- If the last assistant turn is an unresolved question, respond with a critique asking it to complete the work.
- Be specific (file/function names) — avoid vague "improve quality" comments."""

_NEXT_AGENT_PROMPT = """You are a handoff coordinator. Based on the conversation so far, decide which agent profile should handle the NEXT step.

Available profiles:
- **architect**: For design decisions, architecture, codebase analysis
- **planner**: For task decomposition and coordination
- **coder**: For writing code
- **reviewer**: For code review and validation
- **debugger**: For debugging and fixing issues
- **qa**: For testing and quality assurance
- **researcher**: For information gathering, codebase exploration, web research
- **security**: For security auditing, vulnerability scanning, threat modeling
- **done**: If the task is complete and no more agents are needed

Respond with ONLY the profile name or "done".
Examples:
"code needs to be written" → coder
"need to review the implementation" → reviewer
"tests fail, need to debug" → debugger
"task is complete" → done
"need to research API usage" → researcher
"audit for security issues" → security
"""


_SECRET_KEYS = ("api_key", "token", "secret", "password", "authorization", "cookie")


def _redact_audit_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ("***" if any(s in k.lower() for s in _SECRET_KEYS) else v) for k, v in args.items()
    }


class TaskOutcomeTracker:
    def __init__(self, max_history: int = 20) -> None:
        self._max_history = max_history
        self._outcomes: dict[str, list[bool]] = {}
        self._consecutive_errors: dict[str, int] = {}

    def record(self, profile: str, success: bool) -> None:
        if profile not in self._outcomes:
            self._outcomes[profile] = []
        self._outcomes[profile].append(success)
        if len(self._outcomes[profile]) > self._max_history:
            self._outcomes[profile] = self._outcomes[profile][-self._max_history:]
        if success:
            self._consecutive_errors[profile] = 0
        else:
            self._consecutive_errors[profile] = self._consecutive_errors.get(profile, 0) + 1

    def success_rate(self, profile: str) -> float:
        history = self._outcomes.get(profile, [])
        if not history:
            return 0.5
        return sum(history) / len(history)

    def consecutive_errors(self, profile: str) -> int:
        return self._consecutive_errors.get(profile, 0)

    def should_escalate(self, profile: str) -> bool:
        return self.consecutive_errors(profile) >= 2

    def suggest_profile(self, failed_profile: str) -> str | None:
        if self.success_rate(failed_profile) < 0.3:
            best = "coder"
            best_rate = 0.0
            for p, history in self._outcomes.items():
                if p != failed_profile and history:
                    rate = sum(history) / len(history)
                    if rate > best_rate:
                        best_rate = rate
                        best = p
            if best_rate > 0.5:
                return best
        return None

    def status(self) -> dict[str, dict[str, Any]]:
        return {
            p: {
                "success_rate": round(self.success_rate(p), 2),
                "consecutive_errors": self.consecutive_errors(p),
                "total": len(h),
            }
            for p, h in self._outcomes.items()
        }


class ProfileMemory:
    def __init__(self, max_files: int = 5) -> None:
        self._max_files = max_files
        self._recent_files: dict[str, list[str]] = {}
        self._patterns: dict[str, list[str]] = {}

    def record_file(self, profile: str, filepath: str) -> None:
        if profile not in self._recent_files:
            self._recent_files[profile] = []
        files = self._recent_files[profile]
        if filepath in files:
            files.remove(filepath)
        files.append(filepath)
        if len(files) > self._max_files:
            files.pop(0)

    def record_pattern(self, profile: str, pattern: str) -> None:
        if profile not in self._patterns:
            self._patterns[profile] = []
        patterns = self._patterns[profile]
        if pattern not in patterns:
            patterns.append(pattern)
            if len(patterns) > 10:
                patterns.pop(0)

    def get_recent_files(self, profile: str) -> list[str]:
        return list(self._recent_files.get(profile, []))

    def get_patterns(self, profile: str) -> list[str]:
        return list(self._patterns.get(profile, []))

    def get_context_hint(self, profile: str) -> str:
        files = self.get_recent_files(profile)
        patterns = self.get_patterns(profile)
        hints: list[str] = []
        if files:
            hints.append(f"Recently modified files: {', '.join(files[-3:])}")
        if patterns:
            hints.append(f"Conventions observed: {', '.join(patterns[-3:])}")
        return "\n".join(hints) if hints else ""


class PlanTracker:
    def __init__(self, steps: list[str]) -> None:
        self._steps = steps
        self._current = 0
        self._completed: list[int] = []
        self._step_tool_calls: dict[int, int] = {i: 0 for i in range(len(steps))}

    @property
    def current_step(self) -> int:
        return self._current

    @property
    def total_steps(self) -> int:
        return len(self._steps)

    @property
    def current_description(self) -> str:
        if self._current < len(self._steps):
            return self._steps[self._current]
        return ""

    def advance(self) -> str | None:
        if self._current < len(self._steps):
            self._completed.append(self._current)
            self._current += 1
            if self._current < len(self._steps):
                return self._steps[self._current]
        return None

    def record_tool_call(self) -> None:
        if self._current < len(self._steps):
            self._step_tool_calls[self._current] = self._step_tool_calls.get(self._current, 0) + 1

    def is_step_stale(self) -> bool:
        if self._current >= len(self._steps):
            return False
        return self._step_tool_calls.get(self._current, 0) >= 5

    def progress_summary(self) -> str:
        done = len(self._completed)
        total = len(self._steps)
        if total == 0:
            return ""
        current_desc = self.current_description
        return f"Plan progress: {done}/{total} steps done. Current step: {current_desc}"

    def build_status_message(self) -> str:
        lines: list[str] = []
        for i, step in enumerate(self._steps):
            if i in self._completed:
                lines.append(f"  [x] {step}")
            elif i == self._current:
                lines.append(f"  [>] {step}  ← current")
            else:
                lines.append(f"  [ ] {step}")
        return "Execution plan:\n" + "\n".join(lines)


class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMRouter,
        tool_registry: ToolRegistry,
        send_fn: Callable[..., Any] | None = None,
        max_total_iterations: int = 50,
        max_handoffs: int = 5,
        planner_enabled: bool = True,
        critic_enabled: bool = True,
        max_critic_passes: int = 2,
        reflect_enabled: bool = True,
        max_retries: int = 1,
    ):
        self._llm = llm
        self._tool_registry = tool_registry
        self._router = IntentRouter(llm)
        self._default_status = StatusEmitter(send_fn)
        self._max_total_iterations = max_total_iterations
        self._max_handoffs = max_handoffs
        self._planner_enabled = planner_enabled
        self._critic_enabled = critic_enabled
        self._max_critic_passes = max_critic_passes
        self._reflect_enabled = reflect_enabled
        self._max_retries = max_retries
        self._outcome_tracker = TaskOutcomeTracker()
        self._profile_memory = ProfileMemory()

    async def execute(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        profile_override: str | None = None,
        on_token: Callable[[str], Any] | None = None,
        status_emitter: StatusEmitter | None = None,
        _retry_depth: int = 0,
    ) -> AgentResult:
        ctx = context or {}
        agent_ctx = self._build_agent_context(query, ctx)

        total_iterations = 0
        handoffs = 0
        tokens_used = 0
        started_at = time.monotonic()
        profile_name = profile_override or (await self._router.classify(query, fallback_profile="coder")).profile
        current_profile = resolve_profile(profile_name)

        st = status_emitter or self._default_status
        await st.agent_started(current_profile.name, query)

        messages: list[dict[str, Any]] = []
        messages.append({"role": "system", "content": self._build_system_prompt(current_profile, ctx, agent_ctx.workspace)})

        safe_query = redact_pii(query)
        messages.append({"role": "user", "content": safe_query})

        workspace_hint = ""
        if agent_ctx.workspace is not None:
            workspace_hint = f"Workspace root: {agent_ctx.workspace}"
        plan_steps = await self._create_plan(safe_query, current_profile, workspace_hint)
        plan_tracker: PlanTracker | None = None
        if plan_steps:
            agent_ctx.plan_steps = plan_steps
            plan_tracker = PlanTracker(plan_steps)
            await st.plan_created(current_profile.name, plan_steps)
            messages.append({"role": "assistant", "content": plan_tracker.build_status_message()})

        stalled_rounds = 0
        last_tool_names: set[tuple[str, str]] = set()
        consecutive_errors = 0
        tool_history_empty = True
        status: AgentStatus = "max_steps"
        content = ""

        while total_iterations < self._max_total_iterations:
            total_iterations += 1
            agent_ctx.iteration = total_iterations

            if len(messages) > 60:
                messages = await self._compress_context(messages, current_profile)

            if stalled_rounds >= 3:
                msg = (
                    "You seem stuck in a loop. Continue with your best assumption; "
                    "if you need clarification, finish your reply with a short question for the user."
                )
                messages.append({"role": "system", "content": msg})
                await st.thinking(current_profile.name, "Self-correction: asking user for guidance")
                stalled_rounds = 0

            if consecutive_errors >= 3:
                msg = (
                    "Several of your recent tool calls failed. Review the error messages, "
                    "verify your arguments against the tool schemas, and change your approach. "
                    "Do NOT re-run the same failing tool with identical arguments."
                )
                messages.append({"role": "system", "content": msg})
                await st.thinking(current_profile.name, "Self-correction: recovering from repeated tool failures")
                consecutive_errors = 0

            if self._reflect_enabled and total_iterations > 6 and not tool_history_empty:
                tool_history_empty = False
                if total_iterations % 4 == 0:
                    await self._maybe_reflect(messages, current_profile, st)

            if plan_tracker and total_iterations % 5 == 0 and plan_tracker.total_steps > 0:
                status_msg = plan_tracker.progress_summary()
                messages.append({"role": "system", "content": status_msg})
                await st.thinking(current_profile.name, status_msg)

            tool_schemas = self._build_tool_schemas(current_profile)

            await st.thinking(current_profile.name, f"Iteration {total_iterations}")

            try:
                safe_messages = [{**m, "content": redact_pii(str(m.get("content", "")))} for m in messages]
                resp = await self._llm.complete(safe_messages, tools=tool_schemas)
                tokens_used += self._estimate_tokens(safe_messages, resp)
                await audit_logger.log(
                    AuditEventType.LLM_CALL,
                    f"agent:{current_profile.name}",
                    detail={"iteration": total_iterations, "profile": current_profile.name, "tokens": tokens_used},
                )
            except Exception as e:
                logger.error("AgentOrchestrator: LLM call failed at iteration {}: {}", total_iterations, e)
                await st.error(current_profile.name, str(e)[:200])
                if total_iterations >= 3:
                    status = "error"
                    break
                continue

            content = resp.content or ""
            tool_calls = resp.tool_calls or []

            if content and on_token:
                on_token(content)

            if not tool_calls:
                stalled_rounds = 0
                last_tool_names = set()
                messages.append({"role": "assistant", "content": content})

                next_profile = await self._maybe_handoff(messages, current_profile, handoffs)
                if next_profile is not None:
                    handoffs += 1
                    await st.handoff(current_profile.name, next_profile.name, "automatic handoff")
                    current_profile = next_profile
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"Role changed to {current_profile.display_name}. "
                                f"Continue with the context above using your new role."
                            ),
                        }
                    )
                    continue

                if self._critic_enabled and agent_ctx.critic_passes < self._max_critic_passes:
                    agent_ctx.critic_passes += 1
                    await st.critic_started(current_profile.name)
                    critique = await self._critique_result(safe_query, messages, current_profile)
                    if critique is not None:
                        messages.append(
                            {
                                "role": "user",
                                "content": f"Review feedback from Critic:\n{critique}\n\nPlease fix the issues above.",
                            }
                        )
                        await st.thinking(current_profile.name, f"Critic pass {agent_ctx.critic_passes}")
                        continue

                status = "success"
                break

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
            assistant_msg["tool_calls"] = [tc.to_dict() for tc in tool_calls]
            messages.append(assistant_msg)

            current_tool_names = {
                (tc.name, json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)) for tc in tool_calls
            }
            if current_tool_names == last_tool_names and current_tool_names:
                stalled_rounds += 1
                logger.warning("AgentOrchestrator: stalled (same tools: {})", current_tool_names)
            else:
                stalled_rounds = 0
            last_tool_names = current_tool_names

            for tc in tool_calls:
                await st.tool_call(current_profile.name, tc.name, tc.arguments)
                await audit_logger.log(
                    AuditEventType.TOOL_EXEC,
                    f"agent:{current_profile.name}",
                    target=tc.name,
                    detail={"args": _redact_audit_args(tc.arguments or {})},
                )
            tool_results = await asyncio.gather(
                *(self._execute_tool_safe(tc, current_profile, agent_ctx) for tc in tool_calls),
                return_exceptions=False,
            )
            round_errors = 0
            round_quality = 0.0
            round_tool_count = len(tool_calls)
            for tc, tool_result in zip(tool_calls, tool_results, strict=True):
                tool_status = "ok" if "error" not in tool_result else "error"
                if tool_status == "error":
                    round_errors += 1
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                await st.tool_result(current_profile.name, tc.name, tool_status)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_result, default=str)})

                round_quality += self._score_tool_result(tool_result)

                if plan_tracker:
                    plan_tracker.record_tool_call()

                if tc.name in ("file_read", "file_write", "edit", "grep", "glob") and not tool_result.get("error"):
                    path_val = (tc.arguments or {}).get("path", "")
                    if path_val and isinstance(path_val, str):
                        self._profile_memory.record_file(current_profile.name, path_val)
                    if tc.name == "grep":
                        pattern_val = (tc.arguments or {}).get("pattern", "")
                        if pattern_val and isinstance(pattern_val, str):
                            self._profile_memory.record_pattern(current_profile.name, pattern_val)

            if plan_tracker and (plan_tracker.is_step_stale() and round_tool_count > 0 and round_quality / round_tool_count < 0.4):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "You have spent many tool calls on the current step without producing useful "
                            "results. Reconsider your approach to this step, verify prerequisites are met, "
                            "and take a different concrete action."
                        ),
                    }
                )

            if plan_tracker and round_tool_count > 0:
                # Advance the plan ONLY when an implementation/verification tool
                # succeeded — never on read/explore tools, so we don't mark a
                # step "done" prematurely while still investigating.
                implementation_succeeded = any(
                    (tc.name in _IMPLEMENT_TOOLS) and ("error" not in tr)
                    for tc, tr in zip(tool_calls, tool_results, strict=True)
                )
                if implementation_succeeded and plan_tracker.current_step < plan_tracker.total_steps:
                    next_step = plan_tracker.advance()
                    if next_step:
                        messages.append({"role": "system", "content": f"Step completed. Next: {next_step}"})
            tool_history_empty = False

        duration = time.monotonic() - started_at
        final_content = content if status == "success" else self._extract_final_content(messages)
        if status == "success" and not final_content:
            status = "error"

        self._outcome_tracker.record(current_profile.name, status == "success")
        self._router.record_outcome(query, current_profile.name, status == "success")
        if status != "success":
            suggested = self._outcome_tracker.suggest_profile(current_profile.name)
            if suggested and self._max_retries > 0 and _retry_depth < self._max_retries:
                logger.info("TaskOutcomeTracker: auto-retrying with profile '{}' (was '{}')", suggested, current_profile.name)
                retry_result = await self.execute(
                    query=query,
                    context=context,
                    profile_override=suggested,
                    on_token=on_token,
                    status_emitter=status_emitter,
                    _retry_depth=_retry_depth + 1,
                )
                retry_result.profile = f"{current_profile.name}→{retry_result.profile}"
                return retry_result

        return AgentResult(
            content=final_content
            or ("Task completed with partial results." if status == "success" else "[error: task failed]"),
            profile=current_profile.name,
            iterations=total_iterations,
            handoffs=handoffs,
            duration=duration,
            tokens_used=tokens_used,
            status=status,
        )

    def _build_agent_context(self, query: str, ctx: dict[str, Any]) -> AgentContext:
        workspace = ctx.get("workspace")
        permissions_raw = ctx.get("permissions") or []
        permissions = frozenset(str(p) for p in permissions_raw if isinstance(p, str))
        return AgentContext(query=query, workspace=Path(workspace) if workspace else None, permissions=permissions)

    def _build_system_prompt(self, profile: AgentProfile, ctx: dict[str, Any], workspace: Path | None) -> str:
        parts: list[str] = [profile.system_prompt]
        style_hint = self._get_style_hint(profile.name)
        if style_hint:
            parts.append(f"Working style: {style_hint}")
        memory_hint = self._profile_memory.get_context_hint(profile.name)
        if memory_hint:
            parts.append(f"Your recent work context:\n{memory_hint}")
        workspace_info = ctx.get("workspace_context", "")
        if workspace_info:
            parts.append(f"Workspace context:\n{workspace_info}")
        if workspace is not None:
            parts.append(f"Allowed workspace root: {workspace}")
        additional = ctx.get("additional_context")
        if additional:
            parts.append(f"Additional context:\n{additional}")
        return "\n\n".join(parts)

    async def _maybe_handoff(
        self, messages: list[dict[str, Any]], current_profile: AgentProfile, handoffs: int
    ) -> AgentProfile | None:
        if not current_profile.can_handoff or handoffs >= self._max_handoffs:
            return None
        next_name = await self._decide_next_agent(messages, current_profile.name)
        if not next_name or next_name == "done" or next_name == current_profile.name:
            return None
        return resolve_profile(next_name)

    def _build_tool_schemas(self, profile: AgentProfile) -> list[dict[str, Any]] | None:
        all_specs = self._tool_registry.list()
        if not all_specs:
            return None
        allowed_specs = profile.allowed_tools
        denied_specs = profile.denied_tools
        if "*" in allowed_specs and "*" not in denied_specs:
            filtered = [s for s in all_specs if s.name not in denied_specs]
        elif "*" in allowed_specs:
            filtered = all_specs
        else:
            allowed = set(allowed_specs)
            denied = set(denied_specs)
            filtered = [s for s in all_specs if s.name in allowed and s.name not in denied]
        if not filtered:
            return None
        return [s.to_llm_tool() for s in filtered]

    def _score_tool_result(self, result: dict[str, Any]) -> float:
        if "error" in result:
            return 0.0
        content = str(result.get("result", ""))
        if not content:
            return 0.1
        if len(content) < 10:
            return 0.3
        if content.startswith("[") and content.endswith("]"):
            return 0.4
        if "success" in content.lower() or "done" in content.lower() or "created" in content.lower():
            return 0.9
        if len(content) > 100:
            return 0.8
        return 0.6

    def _get_style_hint(self, profile_name: str) -> str:
        hints = {
            "debugger": "Be precise, methodical, and conservative. Test each hypothesis before acting.",
            "reviewer": "Be thorough but concise. Focus on correctness and security.",
            "qa": "Be systematic and exhaustive. Test edge cases and boundary conditions.",
            "security": "Be rigorous and threat-focused. Consider all attack vectors.",
            "architect": "Be thoughtful about trade-offs. Consider scalability and maintainability.",
            "planner": "Be structured and dependency-aware. Order steps logically.",
            "coder": "Be productive and follow existing patterns. Verify your work.",
            "researcher": "Be curious and thorough. Cross-check findings from multiple sources.",
        }
        return hints.get(profile_name, "")

    async def _compress_context(
        self, messages: list[dict[str, Any]], profile: AgentProfile
    ) -> list[dict[str, Any]]:
        system = messages[0]
        recent = messages[-15:]
        middle = messages[1:-15]
        if not middle:
            return messages
        summary_parts: list[str] = []
        for m in middle:
            role = m.get("role", "")
            content = str(m.get("content", ""))[:200]
            if role == "tool":
                summary_parts.append(f"[tool result: {content[:100]}]")
            elif role == "assistant":
                summary_parts.append(f"[assistant: {content[:150]}]")
            elif role == "user":
                summary_parts.append(f"[user: {content[:150]}]")
            elif role == "system":
                summary_parts.append(f"[system: {content[:150]}]")
        summary = "\n".join(summary_parts[-20:])
        return [
            system,
            {"role": "system", "content": f"[Conversation summary]\n{summary}"},
            *recent,
        ]

    async def _execute_tool_safe(
        self, tc: ToolCall, profile: AgentProfile, agent_ctx: AgentContext
    ) -> dict[str, Any]:
        tool_spec = self._tool_registry.get(tc.name)
        if not tool_spec:
            return {"error": f"Unknown tool: {tc.name}"}
        if tc.name in profile.denied_tools:
            return {"error": f"Tool '{tc.name}' denied by profile '{profile.name}'"}
        if agent_ctx.permissions and tc.name not in agent_ctx.permissions:
            return {"error": f"Tool '{tc.name}' not allowed by context permissions"}

        args = tc.arguments or {}
        validation_error = validate_tool_arguments(tc.name, tool_spec.parameters, args)
        if validation_error is not None:
            logger.warning("AgentOrchestrator: {} — handler not invoked", validation_error)
            return {"error": validation_error}

        try:
            self._check_security_policy(tc, agent_ctx.workspace)
            result = await self._tool_registry.call(tc.name, **args)
            return {"result": str(result)[:5000]}
        except ValueError as e:
            logger.warning("Tool {} blocked by security policy: {}", tc.name, e)
            return {"error": str(e)[:500]}
        except Exception as e:
            logger.error("Tool {} failed: {}", tc.name, e)
            return {"error": str(e)[:500]}

    def _check_security_policy(self, tc: ToolCall, workspace: Path | None) -> None:
        args = tc.arguments or {}
        for pk in _PATH_KEYS:
            val = args.get(pk)
            if not val or not isinstance(val, str):
                continue
            from raven.core.security.ssrf import validate_url
            from raven.core.security.tool_policy import _resolve_safe

            if val.startswith(("http://", "https://")):
                block_reason = validate_url(val)
                if block_reason is not None:
                    raise ValueError(f"SSRF blocked: {block_reason}")
            ws = workspace or settings.resolved_workspace
            if ws is not None and not val.startswith(("http://", "https://", "data:", "file:")):
                resolved = _resolve_safe(val, ws)
                if resolved is None:
                    raise ValueError(f"Path '{val}' is outside workspace or invalid")

    async def _create_plan(self, query: str, profile: AgentProfile, workspace_hint: str = "") -> list[str]:
        if not self._planner_enabled:
            return []
        try:
            from raven.core.model_tiers import select_model, tiers_configured

            user_msg = f"Request: {query}\nCurrent role: {profile.display_name}"
            if workspace_hint:
                user_msg += f"\n{workspace_hint}"
            plan_messages = [
                {"role": "system", "content": _PLAN_PROMPT},
                {"role": "user", "content": user_msg},
            ]
            resp = await self._llm.complete(
                plan_messages,
                model=select_model(plan_messages, prefer_tier="fast") if tiers_configured() else "",
            )
            return _parse_plan_steps(resp.content or "")
        except Exception as e:
            logger.debug("Plan generation failed, continuing without a plan: {}", e)
            return []

    async def _critique_result(
        self, query: str, messages: list[dict[str, Any]], profile: AgentProfile
    ) -> str | None:
        last_content = ""
        for m in reversed(messages):
            if isinstance(m.get("content"), str) and m["content"]:
                last_content = m["content"]
                break
        try:
            resp = await self._llm.complete(
                [
                    {"role": "system", "content": _CRITIC_PROMPT},
                    {
                        "role": "user",
                        "content": f"Goal: {query}\n\nAssistant output so far:\n{last_content[:4000]}",
                    },
                ],
                model="",
            )
            text = (resp.content or "").strip()
            if not text or re.match(r"^\s*ACCEPT(?:\s|$)", text.upper()):
                return None
            return text[:800] or None
        except Exception as e:
            logger.debug("Critique failed, accepting current result: {}", e)
            return None

    async def _maybe_reflect(
        self,
        messages: list[dict[str, Any]],
        profile: AgentProfile,
        st: StatusEmitter,
    ) -> None:
        """Periodically ask the LLM to consolidate progress so long tasks don't drift.

        Injects a lightweight progress-synthesis prompt every few iterations. The
        result is appended as an assistant-style context note to keep subsequent
        reasoning anchored without burning the whole tool budget on tool calls.
        """
        try:
            tail = "\n".join(f"{m['role']}: {(m.get('content') or '')[:400]}" for m in messages[-8:])
            resp = await self._llm.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are helping a long-running agent stay on track. "
                            "Summarize, in 1-2 short sentences, what has been accomplished "
                            "so far and the single most important next action. Do not call tools."
                        ),
                    },
                    {"role": "user", "content": f"Recent activity:\n{tail[:3000]}"},
                ],
                model="",
            )
            summary = (resp.content or "").strip()
            if not summary:
                return
            messages.append({"role": "system", "content": f"[progress checkpoint]\n{summary[:500]}"})
            await st.thinking(profile.name, f"Reflection: {summary[:200]}")
        except Exception as e:
            logger.debug("Reflection step failed, continuing: {}", e)

    async def _decide_next_agent(self, messages: list[dict[str, Any]], current_profile: str) -> str | None:
        try:
            resp = await self._llm.complete(
                [
                    {"role": "system", "content": _NEXT_AGENT_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Current agent: {current_profile}\n"
                            f"Conversation summary (last messages):\n"
                            + "\n".join(f"{m['role']}: {(m.get('content') or '')[:300]}" for m in messages[-6:])
                        ),
                    },
                ],
                model="",
            )
            decision = (resp.content or "").strip().lower()
            if decision in _VALID_HANDOFF_PROFILES and decision != "done":
                return None if decision == current_profile else decision
            return None
        except Exception as e:
            logger.debug("Handoff decision failed: {}", e)
            return None

    def _estimate_tokens(self, messages: list[dict[str, Any]], resp: LLMResponse) -> int:
        total = 0
        for m in messages:
            total += len(str(m.get("content", ""))) // 4
        total += len(resp.content or "") // 4
        return total

    def _extract_final_content(self, messages: list[dict[str, Any]]) -> str:
        for m in reversed(messages):
            content = m.get("content")
            if m.get("role") == "assistant" and isinstance(content, str) and content:
                return content
        return ""

    async def execute_with_stream(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        profile_override: str | None = None,
    ) -> AsyncIterator[str]:
        tokens: list[str] = []

        def on_token(t: str) -> None:
            tokens.append(t)

        result = await self.execute(
            query=query,
            context=context,
            profile_override=profile_override,
            on_token=on_token,
        )
        if tokens:
            yield "".join(tokens)
        else:
            yield result.content


def _parse_plan_steps(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    steps = [str(s).strip() for s in parsed if isinstance(s, str) and s.strip()]
    return steps[:8]
