from __future__ import annotations

import asyncio
import contextvars
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from loguru import logger

from raven.core.agents.truthful_orchestrator import TruthfulResult
from raven.core.llm.protocol import LLMClientProtocol
from ravencode.api.client import AIOSClient
from ravencode.core.prompts import get_prompt
from ravencode.runtime.context import Conversation, MemoryStore
from ravencode.runtime.permissions import PermissionManager, default_deny_rules
from ravencode.runtime.question import QuestionError
from ravencode.runtime.tools import (
    execute_tool,
    get_tool_definitions,
    is_dangerous,
    set_permission_checker,
)

# ---------------------------------------------------------------------------
# event system
# ---------------------------------------------------------------------------


@dataclass
class AgentEvent:
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class EventEmitter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[AgentEvent], Awaitable[None]]]] = {}

    def on(self, event_type: str, handler: Callable[[AgentEvent], Awaitable[None]]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def emit(self, event: AgentEvent) -> None:
        handlers = self._handlers.get(event.type, [])
        if len(handlers) <= 1:
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as exc:
                    logger.exception("Event handler failed for {}: {}", event.type, exc)
            return
        results = await asyncio.gather(
            *(self._safe_handle(h, event) for h in handlers),
            return_exceptions=True,
        )
        for _h, res in zip(handlers, results, strict=True):
            if isinstance(res, Exception):
                logger.exception("Event handler failed for {}: {}", event.type, res)

    @staticmethod
    async def _safe_handle(handler: Callable[[AgentEvent], Awaitable[None]], event: AgentEvent) -> None:
        await handler(event)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


class AgentConfig:
    def __init__(
        self,
        max_steps: int = 30,
        max_tool_retries: int = 3,
        confirm_dangerous: bool = True,
        confirm_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        diff_preview: bool = True,
        proactive_scan: bool = True,
        structured_output: bool = False,
        memory_path: str | None = None,
        llm_timeout: int = 120,
        event_emitter: EventEmitter | None = None,
        on_step: Callable[[str, int], Awaitable[None]] | None = None,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        plan_mode: bool = False,
        permissions: PermissionManager | None = None,
        use_cache: bool = True,
        auto_format: bool = True,
    ):
        self.max_steps = max_steps
        self.max_tool_retries = max_tool_retries
        self.confirm_dangerous = confirm_dangerous
        self.confirm_callback = confirm_callback
        self.diff_preview = diff_preview
        self.proactive_scan = proactive_scan
        self.structured_output = structured_output
        self.memory_path = memory_path
        self.llm_timeout = llm_timeout
        self.event_emitter = event_emitter
        self.on_step = on_step
        self.on_message = on_message
        self.plan_mode = plan_mode
        self.permissions = permissions
        self.use_cache = use_cache
        self.auto_format = auto_format

    @classmethod
    def safe(cls) -> Self:
        return cls(confirm_dangerous=True, diff_preview=True, proactive_scan=True, max_steps=30)

    @classmethod
    def fast(cls) -> Self:
        return cls(confirm_dangerous=False, diff_preview=False, proactive_scan=False, max_steps=50)

    @classmethod
    def autonomous(cls) -> Self:
        return cls(confirm_dangerous=False, diff_preview=True, proactive_scan=True, max_steps=100)

    @classmethod
    def plan(cls) -> Self:
        return cls(
            plan_mode=True,
            confirm_dangerous=False,
            diff_preview=False,
            proactive_scan=True,
            max_steps=30,
            structured_output=True,
        )


# ---------------------------------------------------------------------------
# ReActAgent
# ---------------------------------------------------------------------------

_last_agent_var: contextvars.ContextVar[ReActAgent | None] = contextvars.ContextVar("_last_agent", default=None)


class ReActAgent:
    @classmethod
    def last_agent(cls) -> ReActAgent | None:
        return _last_agent_var.get()

    def __init__(
        self,
        config: AgentConfig | None = None,
        conversation: Conversation | None = None,
        llm_provider: Any = None,
        name: str = "raven",
        max_steps: int | None = None,
    ):
        self.config = config or AgentConfig()
        if max_steps is not None:
            self.config.max_steps = max_steps
        self.name = name
        if conversation is None:
            memory = MemoryStore(path=self.config.memory_path) if self.config.memory_path else None
            self.conversation = Conversation(system_prompt=self._build_system_prompt(), memory=memory)
        else:
            self.conversation = conversation
        self.llm_provider = llm_provider
        self._lock = asyncio.Lock()
        self._aborted = False
        self._task: asyncio.Task[Any] | None = None

        self._init_permissions()

    def _init_permissions(self) -> None:
        if self.config.plan_mode:
            denier = PermissionManager(rules=default_deny_rules())
            set_permission_checker(lambda name, args: denier.is_allowed(name, args))
        elif self.config.permissions is not None:
            pm = self.config.permissions
            set_permission_checker(lambda name, args: pm.is_allowed(name, args))
        else:
            set_permission_checker(lambda name, args: (True, ""))

    # -----------------------------------------------------------------------
    # system prompt
    # -----------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = Path(__file__).parent.parent / "agents" / "AGENTS.md"
        base = prompt.read_text(encoding="utf-8") if prompt.is_file() else self._default_system_prompt()
        extras = []
        if self.config.structured_output:
            extras.append(get_prompt("structured_output_instruction"))
        if self.config.plan_mode:
            extras.append(get_prompt("plan_mode_instruction"))
        if self.config.proactive_scan:
            extras.append(get_prompt("proactive_scan_instruction"))
        if self.config.diff_preview:
            extras.append(get_prompt("diff_preview_instruction"))
        if extras:
            base += "\n\n" + "\n".join(extras)
        base += self._artifact_blocks()
        return base

    def _artifact_blocks(self) -> str:
        try:
            from raven.core.artifacts import get_artifact_manager

            root = Path.cwd()
            manager = get_artifact_manager(cwd=root)
            ctx = manager.context(agent_id=self.name, cwd=root, root=root)
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

    @staticmethod
    def _default_system_prompt() -> str:
        return get_prompt("system")

    # -----------------------------------------------------------------------
    # core loop
    # -----------------------------------------------------------------------

    def abort(self) -> None:
        self._aborted = True
        if self._task is not None:
            self._task.cancel()

    async def run_truthful(
        self,
        user_input: str,
        completer: LLMClientProtocol,
        model: str = "",
        context: str = "",
    ) -> TruthfulResult:
        """Run a single query through the Truthful Orchestrator (Chain-of-Verification)."""
        from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

        result = await TruthfulOrchestrator(completer, model=model).process(user_input, context)

        self.conversation.add_user_message(user_input)
        self.conversation.add_assistant_message(result.content)

        ee = self.config.event_emitter
        if ee:
            await ee.emit(
                AgentEvent(
                    "truthful",
                    {
                        "status": result.status,
                        "query": user_input,
                        "content": result.content,
                        "thinking_process": result.thinking_process,
                    },
                )
            )
            await ee.emit(AgentEvent("message", {"role": "assistant", "content": result.content}))
            await ee.emit(AgentEvent("done", {"reason": "truthful", "steps": 1}))
        return result

    async def run(self, user_input: str, images: list[str] | None = None) -> str:
        self._task = asyncio.current_task()
        from ravencode.runtime.tools import set_agent_memory

        _last_agent_var.set(self)
        content = self._build_message_content(user_input, images)
        set_agent_memory(
            {
                "name": self.name,
                "config": {k: v for k, v in self.config.__dict__.items() if not callable(v) and not k.startswith("_")},
                "messages": self.conversation.messages[-6:] if self.conversation.messages else [],
            }
        )
        async with self._lock:
            try:
                return await self._run_impl(user_input, content)
            except asyncio.CancelledError:
                self._aborted = True
                await self._auto_save("aborted")
                return "[aborted]"
            except Exception as exc:
                logger.exception("Agent crashed: {}", exc)
                await self._auto_save(f"crashed: {exc}")
                return f"[error: {exc}]"

    @staticmethod
    def _build_message_content(user_input: str, images: list[str] | None) -> str | list[dict[str, Any]]:
        if not images:
            return user_input
        blocks: list[dict[str, Any]] = [{"type": "text", "text": user_input}]
        for img in images:
            url = img
            if not (img.startswith("http") or img.startswith("data:")):
                url = f"data:image/png;base64,{img}"
            blocks.append({"type": "image_url", "image_url": {"url": url}})
        return blocks

    async def _run_impl(self, user_input: str, content: str | list[dict[str, Any]] | None = None) -> str:
        self.conversation.add_user_message(content if content is not None else user_input)
        self._aborted = False
        step = 0

        ee = self.config.event_emitter

        if self.config.proactive_scan:
            await self._proactive_scan(user_input)

        while step < self.config.max_steps:
            step += 1
            if self._aborted:
                if ee:
                    await ee.emit(AgentEvent("done", {"reason": "aborted", "steps": step}))
                await self._auto_save("aborted")
                return "[aborted]"

            messages = self.conversation.get_messages()
            response = await self._llm_call(messages)

            if not response.get("tool_calls"):
                final = response.get("content", "") or ""
                self.conversation.add_assistant_message(final)
                if ee:
                    await ee.emit(AgentEvent("message", {"role": "assistant", "content": final, "step": step}))
                if self.config.on_step:
                    await self.config.on_step(final, step)
                if self.config.on_message:
                    await self.config.on_message({"role": "assistant", "content": final})
                if ee:
                    await ee.emit(AgentEvent("done", {"reason": "complete", "steps": step}))
                await self._auto_save("complete")
                return final

            content = response.get("content", "") or ""
            tool_calls = response["tool_calls"]

            if content:
                self.conversation.add_assistant_message(content)

            if ee:
                await ee.emit(AgentEvent("step_start", {"step": step, "content": content, "tool_calls": tool_calls}))

            for tc in tool_calls:
                name = tc["function"]["name"]
                raw = tc["function"]["arguments"]

                malformed = ""
                if isinstance(raw, str):
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        args = {}
                        malformed = (
                            f"[error] malformed JSON in tool arguments for '{name}': {raw[:500]!r}. "
                            "Respond with a corrected arguments object."
                        )
                else:
                    args = raw

                if not isinstance(args, dict):
                    args = {"value": str(args)}

                if ee:
                    await ee.emit(AgentEvent("tool_call", {"name": name, "args": args, "step": step}))

                if malformed:
                    result = malformed
                elif await self._confirm_action(name, args):
                    result = await self._execute_with_retry(name, args)
                else:
                    result = f"[user denied] {name} was not approved"

                result_truncated = result[:10_000]
                self.conversation.add_tool_result(tc.get("id", ""), result_truncated)

                if ee:
                    await ee.emit(AgentEvent("tool_result", {"name": name, "result": result_truncated, "step": step}))

                if self.config.on_message:
                    await self.config.on_message(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result_truncated,
                        }
                    )

                if self.config.on_step:
                    await self.config.on_step(f"[tool] {name}: {result_truncated[:200]}", step)

        if ee:
            await ee.emit(AgentEvent("done", {"reason": "max_steps", "steps": step}))
        await self._auto_save("max_steps")
        return "[reached max steps]"

    # -----------------------------------------------------------------------
    # proactive scan
    # -----------------------------------------------------------------------

    async def _proactive_scan(self, user_input: str) -> None:
        scan_prompt = (
            f"Given this task: {user_input}\n\n"
            "Explore the project structure. List up to 20 relevant files clustered by concern. "
            "Return only the file paths, one per line."
        )
        messages = [{"role": "user", "content": scan_prompt}]
        try:
            response = await self._llm_call(messages)
            content = response.get("content", "")
            if content:
                self.conversation.add_user_message(f"[proactive scan of task: {user_input}]\n{content}")
        except Exception as exc:
            logger.debug("Proactive scan failed: {}", exc)

    # -----------------------------------------------------------------------
    # confirmation
    # -----------------------------------------------------------------------

    async def _confirm_action(self, name: str, args: dict[str, Any]) -> bool:
        if not is_dangerous(name):
            return True
        if self.config.plan_mode:
            logger.info("Blocked dangerous tool '{}' in plan mode (read-only)", name)
            return False
        if not self.config.confirm_dangerous:
            return True
        if self.config.confirm_callback is not None:
            return await self.config.confirm_callback(name, args)
        logger.warning(
            "Dangerous tool '{}' auto-approved: confirm_dangerous is set but no confirm_callback is wired",
            name,
        )
        return True

    # -----------------------------------------------------------------------
    # diff preview
    # -----------------------------------------------------------------------

    async def _diff_preview(self, name: str, args: dict[str, Any]) -> str | None:
        if not self.config.diff_preview or name != "edit":
            return None
        if args.get("preview"):
            return None
        preview_args = {**args, "preview": True}
        result = await execute_tool(name, preview_args)
        return result if isinstance(result, str) and result.startswith("[diff") else None

    # -----------------------------------------------------------------------
    # execution
    # -----------------------------------------------------------------------

    async def _execute_with_retry(self, name: str, args: dict[str, Any]) -> str:
        last_err = ""
        for attempt in range(self.config.max_tool_retries):
            try:
                if self.config.diff_preview and name in ("edit", "smart_edit", "patch"):
                    diff = await self._diff_preview(name, args)
                    if diff and not args.get("preview"):
                        preview_msg = f"[diff preview required] Read this diff and confirm:\n{diff}\n\n"
                        result = await execute_tool(name, args)
                        if isinstance(result, list):
                            result = "\n".join(str(r) for r in result[:200])
                        return preview_msg + str(result)
                    if args.get("preview"):
                        result = await execute_tool(name, args)
                        return str(result) if isinstance(result, str) else "\n".join(str(r) for r in result[:200])

                result = await execute_tool(name, args)
                if isinstance(result, list):
                    result = "\n".join(str(r) for r in result[:200])
                final = str(result)

                if self.config.auto_format and name in ("write", "edit", "smart_edit", "patch"):
                    path = args.get("path", "")
                    if path:
                        try:
                            from ravencode.runtime.formatters import format_file

                            fmt_result = await format_file(path)
                            if fmt_result and not fmt_result.startswith("[skipped"):
                                logger.info("Auto-formatted: {}", fmt_result)
                        except Exception as e:
                            logger.debug("Auto-format failed for {}: {}", path, e)
                return final
            except QuestionError:
                raise
            except Exception as exc:
                last_err = str(exc)
                logger.warning("Tool call attempt {}/{} failed: {}", attempt + 1, self.config.max_tool_retries, exc)
                delay = 2**attempt
                await asyncio.sleep(delay)
        return f"[error after {self.config.max_tool_retries} attempts]: {last_err}"

    # -----------------------------------------------------------------------
    # LLM call
    # -----------------------------------------------------------------------

    async def _llm_call(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.llm_provider is not None:
            result = await self.llm_provider(messages)
            return result if isinstance(result, dict) else {"content": str(result)}

        client = AIOSClient()
        tool_defs = get_tool_definitions(plan_mode=self.config.plan_mode)

        try:
            async with asyncio.timeout(self.config.llm_timeout):
                resp = await client.ask_messages(messages, tools=tool_defs)
        except TimeoutError:
            return {"content": "[error: LLM call timed out]", "tool_calls": []}

        tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("arguments", {})),
                },
            }
            for tc in resp.tool_calls
        ]
        output: dict[str, Any] = {"content": resp.text or ""}
        if tool_calls:
            output["tool_calls"] = tool_calls
        return output

    # -----------------------------------------------------------------------
    # auto-save
    # -----------------------------------------------------------------------

    async def _auto_save(self, reason: str) -> None:
        try:
            from ravencode.runtime.session import get_session_store

            store = get_session_store()
            summary = (
                self.conversation.get_messages()[-1].get("content", "")[:200] if self.conversation.messages else reason
            )
            await store.save(self, summary=summary)
        except Exception as exc:
            logger.debug("Auto-save skipped: {}", exc)

    # -----------------------------------------------------------------------
    # serialization
    # -----------------------------------------------------------------------

    def dump_state(self) -> dict[str, Any]:
        cfg = {k: v for k, v in self.config.__dict__.items() if not callable(v) and not k.startswith("_")}
        return {
            "name": self.name,
            "config": cfg,
            "conversation": self.conversation.messages,
            "memory": self.conversation.memory.to_dict() if hasattr(self.conversation, "memory") else {},
        }

    @classmethod
    def load_state(cls, state: dict[str, Any], llm_provider: Any = None) -> Self:
        cfg_data = state.get("config", {})
        cfg_data = {k: v for k, v in cfg_data.items() if not callable(v) and not k.startswith("_")}
        cfg = AgentConfig(**cfg_data)
        conv = Conversation(messages=state.get("conversation", []))
        return cls(config=cfg, conversation=conv, llm_provider=llm_provider, name=state.get("name", "raven"))
