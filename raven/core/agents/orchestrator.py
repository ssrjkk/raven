from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.agents.profiles import AgentProfile, resolve_profile
from raven.core.agents.router import IntentRouter
from raven.core.audit import AuditEventType, audit_logger
from raven.core.config import settings
from raven.core.security.context_filter import redact_pii

if TYPE_CHECKING:
    from raven.core.llm import LLMResponse, LLMRouter, ToolCall
    from raven.core.task_engine.tool_registry import ToolRegistry


@dataclass
class AgentContext:
    profile: AgentProfile
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    started_at: float = 0.0
    tokens_used: int = 0
    handoff_count: int = 0


@dataclass
class AgentResult:
    content: str
    profile: str
    iterations: int
    handoffs: int
    duration: float
    tokens_used: int
    success: bool


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
        await self.emit("handoff", to_profile, f"{from_profile} → {to_profile}: {reason}",
                        {"from": from_profile, "to": to_profile})

    async def plan_created(self, profile: str, steps: list[str]) -> None:
        await self.emit("plan_created", profile, f"Plan: {len(steps)} steps", {"steps": steps})


_NEXT_AGENT_PROMPT = """You are a handoff coordinator. Based on the conversation so far, decide which agent profile should handle the NEXT step.

Available profiles:
- **architect**: For design decisions, architecture, codebase analysis
- **planner**: For task decomposition and coordination
- **coder**: For writing code
- **reviewer**: For code review and validation
- **debugger**: For debugging and fixing issues
- **qa**: For testing and quality assurance
- **done**: If the task is complete and no more agents are needed

Respond with ONLY the profile name or "done".
Examples:
"code needs to be written" → coder
"need to review the implementation" → reviewer
"tests fail, need to debug" → debugger
"task is complete" → done
"""


class AgentOrchestrator:
    def __init__(
        self,
        llm: LLMRouter,
        tool_registry: ToolRegistry,
        send_fn: Callable[..., Any] | None = None,
        max_total_iterations: int = 50,
        max_handoffs: int = 5,
    ):
        self._llm = llm
        self._tool_registry = tool_registry
        self._router = IntentRouter(llm)
        self._default_status = StatusEmitter(send_fn)
        self._max_total_iterations = max_total_iterations
        self._max_handoffs = max_handoffs

    async def execute(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        profile_override: str | None = None,
        on_token: Callable[[str], Any] | None = None,
        status_emitter: StatusEmitter | None = None,
    ) -> AgentResult:
        ctx = context or {}
        total_iterations = 0
        handoffs = 0
        tokens_used = 0
        started_at = time.monotonic()
        profile_name = profile_override or (await self._router.classify(query, fallback_profile="coder")).profile
        profile = resolve_profile(profile_name)
        messages: list[dict[str, Any]] = []
        current_profile = profile

        st = status_emitter or self._default_status
        await st.agent_started(current_profile.name, query)

        workspace_info = ctx.get("workspace_context", "")
        if workspace_info:
            messages.append({"role": "system", "content": f"Workspace context:\n{workspace_info}"})

        system_msg: dict[str, Any] = {"role": "system", "content": current_profile.system_prompt}
        if ctx.get("additional_context"):
            system_msg["content"] += f"\n\nAdditional context:\n{ctx['additional_context']}"
        messages.append(system_msg)

        safe_query = redact_pii(query)
        messages.append({"role": "user", "content": safe_query})

        stalled_rounds = 0
        last_tool_names: set[str] = set()

        for _iteration in range(self._max_total_iterations):
            if total_iterations >= self._max_total_iterations:
                await st.agent_completed(current_profile.name, "max iterations reached")
                break

            total_iterations += 1

            if stalled_rounds >= 3:
                msg = "I've been trying different approaches but keep hitting the same issue. Could you clarify or simplify what you need?"
                messages.append({"role": "user", "content": msg})
                await st.thinking(current_profile.name, "Self-correction: asking user for guidance")
                stalled_rounds = 0

            tool_schemas = self._build_tool_schemas(current_profile)

            await st.thinking(current_profile.name, f"Iteration {total_iterations}")

            try:
                safe_messages = [{**m, "content": redact_pii(str(m.get("content", "")))} for m in messages]
                resp = await self._llm.complete(safe_messages, tools=tool_schemas)
                tokens_used += self._estimate_tokens(safe_messages, resp)
                await audit_logger.log(AuditEventType.LLM_CALL, f"agent:{current_profile.name}", detail={
                    "iteration": total_iterations, "profile": current_profile.name, "tokens": tokens_used,
                })
            except Exception as e:
                logger.error("AgentOrchestrator: LLM call failed at iteration {}: {}", total_iterations, e)
                await st.error(current_profile.name, str(e)[:200])
                if total_iterations >= 3:
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
                result_content = content

                if current_profile.can_handoff and handoffs < self._max_handoffs:
                    next_profile = await self._decide_next_agent(messages, current_profile.name)
                    if next_profile and next_profile != "done" and next_profile != current_profile.name:
                        handoffs += 1
                        await st.handoff(current_profile.name, next_profile, "automatic handoff")
                        current_profile = resolve_profile(next_profile)
                        messages.append({"role": "system", "content": (
                            f"Role changed to {current_profile.display_name}. "
                            f"Continue with the context above using your new role."
                        )})
                        continue

                await st.agent_completed(current_profile.name, "task complete")
                duration = time.monotonic() - started_at
                return AgentResult(
                    content=result_content or content,
                    profile=current_profile.name,
                    iterations=total_iterations,
                    handoffs=handoffs,
                    duration=duration,
                    tokens_used=tokens_used,
                    success=True,
                )

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
            assistant_msg["tool_calls"] = [tc.to_dict() for tc in tool_calls]
            messages.append(assistant_msg)

            current_tool_names = {tc.name for tc in tool_calls}
            if current_tool_names == last_tool_names and current_tool_names:
                stalled_rounds += 1
                logger.warning("AgentOrchestrator: stalled (same tools: {})", current_tool_names)
            else:
                stalled_rounds = 0
            last_tool_names = current_tool_names

            for tc in tool_calls:
                await st.tool_call(current_profile.name, tc.name, tc.arguments)
                await audit_logger.log(AuditEventType.TOOL_EXEC, f"agent:{current_profile.name}",
                                       target=tc.name, detail={"args": tc.arguments})
                tool_result = await self._execute_tool_safe(tc, current_profile)
                tool_status = "ok" if "error" not in tool_result else "error"
                await st.tool_result(current_profile.name, tc.name, tool_status)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                })

        duration = time.monotonic() - started_at
        final_content = messages[-1]["content"] if isinstance(messages[-1].get("content"), str) else ""
        return AgentResult(
            content=final_content or "Task completed with partial results.",
            profile=current_profile.name,
            iterations=total_iterations,
            handoffs=handoffs,
            duration=duration,
            tokens_used=tokens_used,
            success=True,
        )

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

    async def _execute_tool_safe(self, tc: ToolCall, profile: AgentProfile) -> dict[str, Any]:
        tool_spec = self._tool_registry.get(tc.name)
        if not tool_spec:
            return {"error": f"Unknown tool: {tc.name}"}
        if tc.name in profile.denied_tools:
            return {"error": f"Tool '{tc.name}' denied by profile '{profile.name}'"}
        try:
            self._check_security_policy(tc)
            result = await self._tool_registry.call(tc.name, **(tc.arguments or {}))
            return {"result": str(result)[:5000]}
        except ValueError as e:
            logger.warning("Tool {} blocked by security policy: {}", tc.name, e)
            return {"error": str(e)[:500]}
        except Exception as e:
            logger.error("Tool {} failed: {}", tc.name, e)
            return {"error": str(e)[:500]}

    def _check_security_policy(self, tc: ToolCall) -> None:
        path_keys = ("path", "file", "directory", "source", "target")
        args = tc.arguments or {}
        for pk in path_keys:
            val = args.get(pk)
            if val and isinstance(val, str):
                from raven.core.security.ssrf import validate_url
                from raven.core.security.tool_policy import _resolve_safe

                if val.startswith(("http://", "https://")):
                    block_reason = validate_url(val)
                    if block_reason is not None:
                        raise ValueError(f"SSRF blocked: {block_reason}")
                ws = settings.resolved_workspace
                if ws and not val.startswith(("http://", "https://", "data:", "file:")):
                    resolved = _resolve_safe(val, ws)
                    if resolved is None:
                        raise ValueError(f"Path '{val}' is outside workspace or invalid")

    async def _decide_next_agent(self, messages: list[dict[str, Any]], current_profile: str) -> str | None:
        try:
            resp = await self._llm.complete(
                [
                    {"role": "system", "content": _NEXT_AGENT_PROMPT},
                    {"role": "user", "content": (
                        f"Current agent: {current_profile}\n"
                        f"Conversation summary (last messages):\n"
                        + "\n".join(
                            f"{m['role']}: {(m.get('content') or '')[:300]}"
                            for m in messages[-6:]
                        )
                    )},
                ],
                model="",
            )
            decision = (resp.content or "").strip().lower()
            valid_profiles = {"architect", "planner", "coder", "reviewer", "debugger", "qa", "done"}
            if decision in valid_profiles and decision != "done":
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
