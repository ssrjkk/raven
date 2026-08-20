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
Each step must be a single sentence describing one concrete action the assistant will take.
Do NOT write any code. Return ONLY a valid JSON array of strings, with no commentary.
Example output:
["Explore the project structure", "Implement the auth module", "Run tests"]"""

_CRITIC_PROMPT = """You are the final reviewer of an automated coding agent. Judge whether the assistant's output fully satisfies the user's goal.
Look for: unmet requirements, unverified code, missing tests, obvious bugs, or security issues.
If the goal is fully met, reply EXACTLY with the single word: ACCEPT
Otherwise reply with a short critique (2-4 sentences) listing the concrete issues that must be fixed before delivery."""

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

    async def execute(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        profile_override: str | None = None,
        on_token: Callable[[str], Any] | None = None,
        status_emitter: StatusEmitter | None = None,
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

        plan_steps = await self._create_plan(safe_query, current_profile)
        if plan_steps:
            agent_ctx.plan_steps = plan_steps
            await st.plan_created(current_profile.name, plan_steps)
            plan_hint = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(plan_steps))
            messages.append({"role": "assistant", "content": f"Execution plan:\n{plan_hint}\n\nProceeding step by step."})

        stalled_rounds = 0
        last_tool_names: set[tuple[str, str]] = set()
        status: AgentStatus = "max_steps"
        content = ""

        while total_iterations < self._max_total_iterations:
            total_iterations += 1
            agent_ctx.iteration = total_iterations

            if len(messages) > 60:
                system = messages[0]
                messages = [
                    system,
                    {"role": "system", "content": "[earlier context truncated to save tokens]"},
                    *messages[-20:],
                ]

            if stalled_rounds >= 3:
                msg = (
                    "You seem stuck in a loop. Continue with your best assumption; "
                    "if you need clarification, finish your reply with a short question for the user."
                )
                messages.append({"role": "system", "content": msg})
                await st.thinking(current_profile.name, "Self-correction: asking user for guidance")
                stalled_rounds = 0

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
            for tc, tool_result in zip(tool_calls, tool_results, strict=True):
                tool_status = "ok" if "error" not in tool_result else "error"
                await st.tool_result(current_profile.name, tc.name, tool_status)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_result)})

        duration = time.monotonic() - started_at
        final_content = content if status == "success" else self._extract_final_content(messages)
        if status == "success" and not final_content:
            status = "error"
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

    async def _create_plan(self, query: str, profile: AgentProfile) -> list[str]:
        if not self._planner_enabled:
            return []
        try:
            from raven.core.model_tiers import select_model, tiers_configured

            plan_messages = [
                {"role": "system", "content": _PLAN_PROMPT},
                {"role": "user", "content": f"Request: {query}\nCurrent role: {profile.display_name}"},
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
