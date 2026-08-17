from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import Enum, auto
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.budget import TokenBudgetTracker, estimate_tokens
from raven.core.config import settings
from raven.core.db import Database
from raven.core.llm import LLMRouter, ToolCall
from raven.core.llm.queue import PRIORITY_LOW, PRIORITY_NORMAL
from raven.core.models import Message, PluginTool, Session


class AgentState(Enum):
    INIT = auto()
    THINK = auto()
    TOOL_CALL = auto()
    TOOL_RESULT = auto()
    ERROR = auto()
    DONE = auto()


class AgentConfig:
    def __init__(
        self,
        agent_id: str = "default",
        system_prompt: str | None = None,
        model: str | None = None,
        max_tool_rounds: int = 10,
        max_history: int = 50,
        use_memory: bool = True,
        stateless: bool = False,
        workspace: str | None = None,
        priority: float = PRIORITY_NORMAL,
    ):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.max_history = 0 if stateless else max_history
        self.use_memory = False if stateless else use_memory
        self.stateless = stateless
        self.workspace = workspace
        self.priority = priority


DEFAULT_SYSTEM_PROMPT = (
    "You are Raven, a personal AI assistant. You are helpful, concise, and friendly.\n"
    "You have access to tools. When you need to use a tool, the model will handle it natively via function calling.\n"
    "After receiving tool results, incorporate them naturally into your response.\n"
    "Keep responses concise but complete. Use markdown for formatting when appropriate."
)


class Agent:
    def __init__(
        self,
        session: Session,
        tools: list[PluginTool],
        db: Database,
        llm: LLMRouter,
        config: AgentConfig | None = None,
        tool_policy: Any = None,
    ):
        self.session = session
        self.tools = tools
        self.db = db
        self.llm = llm
        self.config = config or AgentConfig()
        self.priority = self.config.priority
        self._tool_map: dict[str, PluginTool] = {t.name: t for t in tools}
        self._tool_policy = tool_policy or self._init_tool_policy()

    def _init_tool_policy(self):
        from raven.core.config import _DEFAULT_TOOLS_DENY, settings
        from raven.core.security.tool_policy import ExecAskMode, ExecSecurity, ToolPolicyEvaluator

        deny_raw = settings.tools_deny
        deny_list = [d.strip() for d in deny_raw.split(",") if d.strip()] if deny_raw else list(_DEFAULT_TOOLS_DENY)
        allow_raw = settings.tools_allow
        allow_list = [a.strip() for a in allow_raw.split(",") if a.strip()] if allow_raw else []
        ws_path = settings.resolved_workspace
        ws_root = str(ws_path) if ws_path else None
        return ToolPolicyEvaluator(
            profile=settings.tools_profile,
            deny=deny_list,
            allow=allow_list,
            exec_security=ExecSecurity(settings.exec_security),
            exec_ask=ExecAskMode(settings.exec_ask_mode),
            workspace_only=settings.workspace_only,
            workspace_root=ws_root,
        )

    async def _build_system_prompt(self) -> str:
        base = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        if self.session.system_prompt:
            base = self.session.system_prompt + "\n\n" + base
        workspace = self.config.workspace
        ws: Path | None = None
        if workspace:
            ws = Path(workspace)
            for fname in ("SOUL.md", "AGENTS.md", "TOOLS.md"):
                fp = ws / fname
                if fp.exists():
                    loop = asyncio.get_running_loop()
                    content = await loop.run_in_executor(None, fp.read_text, "utf-8")
                    content = content.strip()
                    if content:
                        base += f"\n\n---\n[{fname}]\n{content}"
        artifact_blocks = await self._artifact_blocks(ws)
        if artifact_blocks:
            base += artifact_blocks
        return base

    async def _artifact_blocks(self, workspace: Path | None) -> str:
        try:
            from raven.core.artifacts import get_artifact_manager

            root = workspace if workspace is not None else settings.resolved_workspace
            if root is None:
                return ""
            manager = get_artifact_manager(cwd=root)
            ctx = manager.context(
                agent_id=self.config.agent_id,
                channel=self.session.channel,
                cwd=root,
                root=root,
            )
            parts: list[str] = []
            rules = manager.rules_for(ctx)
            if rules:
                body = "\n\n".join(f"[rules: {r.name}]\n{r.content}" for r in rules)
                parts.append(f"[project rules]\n{body}")
            skills = manager.skills_for(ctx)
            for skill in skills:
                text = skill.instructions
                if skill.examples:
                    text = f"{text}\n\nExamples:\n" + "\n\n".join(skill.examples)
                parts.append(f"[skill: {skill.name}]\n{text}")
            commands = manager.commands_for(ctx)
            if commands:
                listing = "\n".join(f"/{c.name} — {c.description}" for c in commands)
                parts.append(f"[available commands]\n{listing}")
            if not parts:
                return ""
            return "\n\n" + "\n\n".join(parts)
        except Exception as e:
            logger.debug("Artifact context skipped: {}", e)
            return ""

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self.tools
        ]

    async def _load_history(self) -> list[dict[str, Any]]:
        msgs = await self.db.get_session_messages(self.session.id, limit=self.config.max_history)
        return [{"role": m.role, "content": m.content} for m in msgs]

    async def _compress(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(messages) <= 6:
            return messages
        conversation = "\n".join(f"{m['role']}: {(m.get('content') or '')[:200]}" for m in messages[:-4])
        prompt = [
            {"role": "system", "content": "Summarize the key points of this conversation concisely in 2-3 sentences."},
            {"role": "user", "content": f"Summarize:\n{conversation}"},
        ]
        try:
            resp = await self.llm.complete(prompt, priority=PRIORITY_LOW)
            summary = (resp.content or "")[:500]
            if summary.strip():
                compressed = [messages[0], {"role": "system", "content": f"[Context summary: {summary}]"}]
                compressed.extend(messages[-4:])
                return compressed
        except Exception as e:
            logger.warning("Compression failed: {}", e)
        return [messages[0], *messages[-8:]] if len(messages) > 8 else messages

    async def _auto_memory(self, user_text: str, response_text: str):
        if not self.config.use_memory:
            return
        recall_tool = self._tool_map.get("search_memory")
        remember_tool = self._tool_map.get("remember")
        if recall_tool and user_text.strip():
            try:
                await recall_tool.handler(query=user_text, n_results=3)
            except Exception as e:
                logger.debug("Auto-recall: {}", e)
        if remember_tool and response_text.strip():
            try:
                await remember_tool.handler(key="auto", value=f"User: {user_text[:300]}")
            except Exception as e:
                logger.debug("Auto-remember: {}", e)

    async def _get_recall_context(self, query: str) -> str | None:
        recall_tool = self._tool_map.get("search_memory")
        if not recall_tool:
            return None
        try:
            result = await recall_tool.handler(query=query, n_results=5)
            text = str(result) if result else ""
            return text if text.strip() and "No relevant memories" not in text else None
        except Exception as e:
            logger.debug("Recall error: {}", e)
            return None

    def _detect_loop(self, history: list[dict[str, Any]]) -> bool:
        tool_calls = [
            m.get("tool_calls", [{}])[0].get("function", {}).get("name", "")
            for m in history
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        if len(tool_calls) < 4:
            return False
        recent = tool_calls[-4:]
        return len(set(recent)) == 1

    async def run(
        self,
        user_message: str,
        recall_context: str | None = None,
        confirm_fn: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        state = AgentState.INIT
        messages: list[dict[str, Any]] = [{"role": "system", "content": await self._build_system_prompt()}]
        self._confirm_fn = confirm_fn
        tool_used = False
        final_content = ""
        consecutive_errors = 0
        delay = 0.5

        if not self.config.stateless and recall_context is None:
            recall_context = await self._get_recall_context(user_message)
        if recall_context:
            messages.append({"role": "system", "content": f"Relevant memories:\n{recall_context}"})

        if not self.config.stateless:
            history = history if history is not None else await self._load_history()
            messages.extend(history[: self.config.max_history])
        messages.append({"role": "user", "content": user_message})

        if not self.config.stateless and len(messages) > self.config.max_history + 3:
            messages = await self._compress(messages)

        _budget_tracker = TokenBudgetTracker()
        _budget_limit = settings.token_budget_per_hour

        schemas = self._tool_schemas() if self.tools else None
        state = AgentState.THINK

        for round_i in range(self.config.max_tool_rounds):
            if state == AgentState.DONE:
                break
            if consecutive_errors >= 3:
                logger.error("Agent: too many consecutive errors, aborting")
                final_content = "I encountered repeated errors and could not complete the request."
                break

            try:
                if self._detect_loop(messages):
                    logger.warning("Agent: detected tool call loop at round {}", round_i)
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "You are repeating the same tool call. Try a different approach or respond directly."
                            ),
                        }
                    )

                input_tokens = estimate_tokens("".join(m.get("content", "") or "" for m in messages))
                if not await _budget_tracker.check_budget(self.session.user_id, input_tokens, 0, _budget_limit, 3600):
                    logger.warning("Token budget exceeded for user {}", self.session.user_id)
                    yield "Your token budget has been exceeded for this hour. Please try again later."
                    state = AgentState.DONE
                    break

                resp = await self.llm.complete(messages, tools=schemas, priority=self.priority)
                consecutive_errors = 0
                delay = 0.5
                content = resp.content or ""

                actual_input = resp.prompt_tokens or input_tokens
                actual_output = resp.completion_tokens or estimate_tokens(content)
                await _budget_tracker.record_usage(self.session.user_id, actual_input + actual_output, _budget_limit, 3600)

                if resp.tool_calls:
                    state = AgentState.TOOL_CALL
                    tool_used = True
                    messages.append(
                        {
                            "role": "assistant",
                            "content": content,
                            "tool_calls": [tc.to_dict() for tc in resp.tool_calls],
                        }
                    )
                    for tc in resp.tool_calls:
                        tool_result = await self._execute_tool(tc)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(tool_result),
                            }
                        )
                        yield f"[{tc.name} → ok]\n"
                    state = AgentState.THINK
                    continue

                final_content = content
                state = AgentState.DONE
                break

            except Exception as e:
                state = AgentState.ERROR
                consecutive_errors += 1
                logger.error("Agent: LLM call failed (round {}/{}): {}", round_i + 1, self.config.max_tool_rounds, e)
                if consecutive_errors < 3:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 8.0)
                    continue
                final_content = "An error occurred while processing your request. Please try again."
                break
        else:
            final_content = "I apologize, but I couldn't complete that request in the allotted steps."

        if final_content:
            yield final_content
        elif tool_used:
            parts: list[str] = []
            async for token in self.llm.complete_stream(messages, priority=self.priority):
                parts.append(token)
                yield token
            final_content = "".join(parts)
        else:
            final_content = "I couldn't generate a response to that. Please try rephrasing your message."
            yield final_content

        if not self.config.stateless:
            user_msg = Message(
                session_id=self.session.id, channel=self.session.channel, role="user", content=user_message
            )
            assistant_msg = Message(
                session_id=self.session.id, channel=self.session.channel, role="assistant", content=final_content
            )
            await self.db.save_message(user_msg)
            await self.db.save_message(assistant_msg)
            await self._auto_memory(user_message, final_content)

    async def _execute_tool(self, tc: ToolCall) -> dict[str, Any]:
        tool = self._tool_map.get(tc.name)
        if not tool:
            logger.warning("Unknown tool: {}", tc.name)
            return {"error": f"Unknown tool: {tc.name}"}
        allowed = self._tool_policy.is_tool_allowed(tc.name)
        if not allowed:
            logger.warning("Tool '{}' denied by policy", tc.name)
            return {"error": f"Tool '{tc.name}' is denied by security policy"}
        if tool.confirm and self._confirm_fn:
            confirmed = await self._confirm_fn(tc.name, tc.arguments or {})
            if not confirmed:
                logger.info("Tool '{}' cancelled by user", tc.name)
                return {"error": f"Tool '{tc.name}' cancelled — user denied confirmation"}
        path_arg = (
            (tc.arguments or {}).get("path")
            or (tc.arguments or {}).get("file")
            or (tc.arguments or {}).get("directory")
        )
        if path_arg and not self._tool_policy.check_path(str(path_arg)):
            return {"error": "Path outside workspace root — denied by security policy"}
        try:
            logger.info("Tool call: {} args={}", tc.name, tc.arguments)
            result = await tool.handler(**(tc.arguments or {}))
            return {"result": str(result)[:4000]}
        except Exception as e:
            logger.error("Tool {} error: {}", tc.name, e)
            return {"error": str(e)[:500]}

    async def simple_complete(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        async for token in self.llm.complete_stream(messages, priority=self.priority):
            yield token
