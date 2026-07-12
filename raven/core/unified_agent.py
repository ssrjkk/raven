from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger

from raven.core.context_router import ContextRouter, TaskType
from raven.core.shared_memory import SharedMemory
from raven.core.tool_registry import ToolRegistry
from ravencode.runtime.agent_core import AgentConfig, EventEmitter, ReActAgent
from ravencode.runtime.permissions import PermissionManager


class AgentMode(StrEnum):
    CODING = "coding"
    AUTOMATION = "automation"
    HYBRID = "hybrid"
    QUERY = "query"


class HybridSession:
    def __init__(self, session_id: str, mode: AgentMode) -> None:
        self.session_id = session_id
        self.messages: list[dict[str, str]] = []
        self.mode = mode
        self.created_at = datetime.now(UTC)

    def add_message(self, role: str, content: str, task_type: str | None = None) -> None:
        entry: dict[str, str] = {"role": role, "content": content}
        if task_type:
            entry["task_type"] = task_type
        self.messages.append(entry)


class UnifiedAgent:
    def __init__(
        self,
        name: str = "raven",
        max_steps: int = 30,
        event_emitter: EventEmitter | None = None,
        permissions: PermissionManager | None = None,
        on_step: Callable[[str, int], Awaitable[None]] | None = None,
        on_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        memory_path: str | None = None,
        llm_provider: Any = None,
        max_context_tokens: int = 128_000,
    ):
        self.name = name
        self._event_emitter = event_emitter or EventEmitter()
        self._permissions = permissions
        self._on_step = on_step
        self._on_message = on_message
        self._memory_path = memory_path
        self._llm_provider = llm_provider
        self._llm_fallbacks: list[Any] = []
        self._router = ContextRouter()
        self._tool_registry = ToolRegistry()
        self._shared_memory = SharedMemory()
        self._max_steps = max_steps
        self._max_context_tokens = max_context_tokens
        self._agent: ReActAgent | None = None
        self._task_type: TaskType = TaskType.QUERY
        self._mode: AgentMode = AgentMode.QUERY
        self._sessions: dict[str, HybridSession] = {}
        self._total_tokens: int = 0

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @property
    def task_type(self) -> TaskType:
        return self._task_type

    @property
    def event_emitter(self) -> EventEmitter:
        return self._event_emitter

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def shared_memory(self) -> SharedMemory:
        return self._shared_memory

    # -- LLM fallback -----------------------------------------------------------

    def add_llm_fallback(self, provider: Any) -> None:
        self._llm_fallbacks.append(provider)

    async def _llm_call_with_fallback(
        self, messages: list[dict[str, Any]], _tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        providers: list[tuple[str, Any]] = [("primary", self._llm_provider)]
        providers.extend((f"fallback_{i}", p) for i, p in enumerate(self._llm_fallbacks))

        first_error: Exception | None = None
        for label, provider in providers:
            if provider is None:
                continue
            try:
                result = await provider(messages)
                return result if isinstance(result, dict) else {"content": str(result)}
            except Exception as exc:
                logger.warning("LLM {} failed: {}", label, exc)
                if first_error is None:
                    first_error = exc

        raise first_error or RuntimeError("No LLM providers available")

    # -- context management ----------------------------------------------------

    def _estimate_tokens(self, messages: list[dict[str, Any]] | list[Any]) -> int:
        total = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "") or ""
            total += len(str(content)) // 4 + 10
        return total

    async def _maybe_summarize(self, agent: ReActAgent) -> bool:
        try:
            raw = agent.conversation.get_messages()
            if hasattr(raw, "__await__"):
                raw = await raw
            messages = raw if isinstance(raw, list) else []
        except Exception as e:
            logger.debug("Failed to get messages for summarization: {}", e)
            return False
        self._total_tokens = self._estimate_tokens(messages)
        if not messages or self._total_tokens < self._max_context_tokens * 0.75:
            return False

        logger.info("Context approaching limit ({} tokens), summarizing...", self._total_tokens)
        history = "\n".join(
            f"{m.get('role', '?')}: {(str(m.get('content', ''))[:300])}"
            for m in messages[:-5]
        )
        summary_prompt = (
            "Summarize the key facts, decisions, and progress from this conversation history "
            "in 2-3 concise sentences. Preserve any user requirements, constraints, and partial work.\n\n"
            f"Conversation history:\n{history}"
        )
        try:
            summary = ""
            if self._llm_provider is not None:
                result = await self._llm_provider([{"role": "user", "content": summary_prompt}])
                summary = result.get("content", "") if isinstance(result, dict) else str(result)
            else:
                from ravencode.api.client import AIOSClient
                client = AIOSClient()
                resp = await client.ask_messages([{"role": "user", "content": summary_prompt}])
                summary = resp.text or ""
            if summary and hasattr(agent.conversation, "messages"):
                keep = messages[-5:] if len(messages) > 5 else messages
                agent.conversation.messages = [
                    {"role": "system", "content": f"[Previous context summarized: {summary[:500]}]"}
                ] + keep
                logger.info("Context summarized from {} messages to {}", len(messages), len(keep) + 1)
                return True
        except Exception as exc:
            logger.info("Context summarization skipped: {}", exc)
        return False

    # -- agent config ----------------------------------------------------------

    def _build_config(self, task_type: TaskType) -> AgentConfig:
        return self._build_agent_config(task_type)

    def _build_agent_config(self, task_type: TaskType) -> AgentConfig:
        mode_configs: dict[TaskType, dict[str, bool]] = {
            TaskType.CODING: {"diff_preview": True, "proactive_scan": True, "plan_mode": False, "structured_output": False},
            TaskType.AUTOMATION: {"diff_preview": False, "proactive_scan": False, "plan_mode": False, "structured_output": False},
            TaskType.HYBRID: {"diff_preview": True, "proactive_scan": True, "plan_mode": False, "structured_output": False},
            TaskType.QUERY: {"diff_preview": True, "proactive_scan": True, "plan_mode": True, "structured_output": True},
        }
        mode_opts = mode_configs.get(task_type, mode_configs[TaskType.QUERY])
        return AgentConfig(
            max_steps=self._max_steps,
            event_emitter=self._event_emitter,
            permissions=self._permissions,
            on_step=self._on_step,
            on_message=self._on_message,
            memory_path=self._memory_path,
            auto_format=True,
            confirm_dangerous=True,
            diff_preview=mode_opts.get("diff_preview", True),
            proactive_scan=mode_opts.get("proactive_scan", True),
            plan_mode=mode_opts.get("plan_mode", False),
            structured_output=mode_opts.get("structured_output", False),
        )

    # -- core dispatch ---------------------------------------------------------

    async def process(self, message: str) -> str:
        await self._classify(message)
        handler = self._get_handler()
        return await handler(message)

    async def stream_process(self, message: str) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        stream_used: list[bool] = [False]

        async def stream_wrapper(msg: dict[str, Any]) -> None:
            if self._on_message:
                await self._on_message(msg)
            content = msg.get("content", "") or msg.get("result", "") or ""
            if content:
                stream_used[0] = True
                await queue.put(content)

        saved_on_message = self._on_message
        self._on_message = stream_wrapper
        task = asyncio.create_task(self._run_and_signal(queue, message, stream_used))

        try:
            while True:
                token = await queue.get()
                if token is None:
                    break
                yield token
            await task
        except Exception as exc:
            logger.error("Stream error: {}", exc)
            yield f"[error: {exc}]"
        finally:
            self._on_message = saved_on_message
            if not task.done():
                task.cancel()

    async def _run_and_signal(self, queue: asyncio.Queue[str | None], message: str, stream_used: list[bool] | None = None) -> None:
        try:
            result = await self.process(message)
            if result and stream_used is not None and not stream_used[0]:
                await queue.put(result)
        except Exception as exc:
            await queue.put(f"[error: {exc}]")
            raise
        finally:
            await queue.put(None)

    async def process_with_recovery(self, message: str, max_retries: int = 2) -> str:
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self.process(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    delay = 2 ** attempt
                    logger.warning("Process attempt {}/{} failed: {} -- retrying in {}s", attempt + 1, max_retries + 1, exc, delay)
                    await asyncio.sleep(delay)
                    self._agent = None
                else:
                    logger.error("All {} process attempts failed: {}", max_retries + 1, exc)
        raise last_error  # type: ignore[misc]

    async def _classify(self, message: str) -> None:
        task_type, confidence = self._router.classify_with_confidence(message)
        self._task_type = task_type
        mode_map: dict[TaskType, AgentMode] = {
            TaskType.CODING: AgentMode.CODING,
            TaskType.AUTOMATION: AgentMode.AUTOMATION,
            TaskType.HYBRID: AgentMode.HYBRID,
            TaskType.QUERY: AgentMode.QUERY,
        }
        self._mode = mode_map[task_type]
        logger.info("Task classified as {} (confidence={:.2f})", task_type.value, confidence)

    def _get_handler(self) -> Callable[[str], Awaitable[str]]:
        handlers: dict[TaskType, Callable[[str], Awaitable[str]]] = {
            TaskType.CODING: self.handle_coding,
            TaskType.AUTOMATION: self.handle_automation,
            TaskType.HYBRID: self.handle_hybrid,
            TaskType.QUERY: self.handle_query,
        }
        return handlers[self._task_type]

    async def process_with_agent(self, message: str, agent: ReActAgent) -> str:
        task_type = self._router.classify(message)
        self._task_type = task_type

        prompt_modifier = self._router.get_system_prompt_modifier(message)
        if prompt_modifier:
            message = f"{message}\n\n[Context: {prompt_modifier}]"

        return await agent.run(message)

    async def _run_with_agent(self, message: str, task_type: TaskType) -> str:
        config = self._build_agent_config(task_type)
        self._agent = ReActAgent(config=config, llm_provider=self._llm_provider, name=self.name)

        prompt_modifier = self._router.get_system_prompt_modifier(message)
        if prompt_modifier:
            message = f"{message}\n\n[Context: {prompt_modifier}]"

        try:
            await self._maybe_summarize(self._agent)
        except Exception as exc:
            logger.debug("summarize failed: {}", exc)

        return await self._agent.run(message)

    async def handle_coding(self, message: str) -> str:
        self._mode = AgentMode.CODING
        self._task_type = TaskType.CODING
        return await self._run_with_agent(message, TaskType.CODING)

    async def handle_automation(self, message: str) -> str:
        self._mode = AgentMode.AUTOMATION
        self._task_type = TaskType.AUTOMATION
        return await self._run_with_agent(message, TaskType.AUTOMATION)

    async def handle_hybrid(self, message: str) -> str:
        self._mode = AgentMode.HYBRID
        self._task_type = TaskType.HYBRID

        coding_result = await self.handle_coding(message)
        automation_message = f"{message}\n\n[Coding result: {coding_result}]"
        automation_result = await self.handle_automation(automation_message)

        return f"[Coding]\n{coding_result}\n\n[Automation]\n{automation_result}"

    async def handle_query(self, message: str) -> str:
        self._mode = AgentMode.QUERY
        self._task_type = TaskType.QUERY
        return await self._run_with_agent(message, TaskType.QUERY)

    def abort(self) -> None:
        if self._agent:
            self._agent.abort()

    # -- session management -----------------------------------------------------

    def create_hybrid_session(self, session_id: str, mode: AgentMode = AgentMode.HYBRID) -> HybridSession:
        session = HybridSession(session_id=session_id, mode=mode)
        self._sessions[session_id] = session
        logger.info("Created hybrid session: {}", session_id)
        return session

    def get_hybrid_session(self, session_id: str) -> HybridSession | None:
        return self._sessions.get(session_id)

    async def process_hybrid_session(self, session_id: str, message: str) -> str:
        session = self._sessions.get(session_id)
        if not session:
            logger.error("Session not found: {}", session_id)
            raise ValueError(f"Hybrid session '{session_id}' not found")

        session.add_message("user", message)

        task_type, confidence = self._router.classify_with_confidence(message)
        self._task_type = task_type
        self._mode = session.mode
        logger.info("Session task classified as {} (confidence={:.2f})", task_type.value, confidence)

        handler = self._get_handler()
        result = await handler(message)

        session.add_message("assistant", result, task_type=task_type.value)
        return result
