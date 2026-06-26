from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Self

from loguru import logger

from ravencode.runtime.context import Conversation
from ravencode.runtime.tools import (
    execute_tool,
    get_tool_definitions,
    is_dangerous,
)

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

    @classmethod
    def safe(cls) -> Self:
        return cls(confirm_dangerous=True, diff_preview=True, proactive_scan=True, max_steps=30)

    @classmethod
    def fast(cls) -> Self:
        return cls(confirm_dangerous=False, diff_preview=False, proactive_scan=False, max_steps=50)

    @classmethod
    def autonomous(cls) -> Self:
        return cls(confirm_dangerous=False, diff_preview=True, proactive_scan=True, max_steps=100)


# ---------------------------------------------------------------------------
# ReActAgent
# ---------------------------------------------------------------------------

class ReActAgent:
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
        self.conversation = conversation or Conversation(system_prompt=self._build_system_prompt())
        self.llm_provider = llm_provider
        self.name = name
        self._lock = asyncio.Lock()
        self._aborted = False

    # -----------------------------------------------------------------------
    # system prompt
    # -----------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        prompt = Path(__file__).parent.parent / "agents" / "AGENTS.md"
        base = prompt.read_text(encoding="utf-8") if prompt.is_file() else self._default_system_prompt()
        extras = []
        if self.config.structured_output:
            extras.append("You must respond with valid JSON only.")
        if self.config.proactive_scan:
            extras.append(
                "Before taking action, first explore the project to find relevant files. "
                "Read existing code to understand conventions before writing new code."
            )
        if self.config.diff_preview:
            extras.append(
                "Before editing a file, read it first and show the diff by calling "
                "edit with preview=true to confirm your changes are correct."
            )
        if extras:
            base += "\n\n" + "\n".join(extras)
        return base

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are Raven, an AI coding assistant.\n"
            "You have tools for reading, writing, editing files, running commands, searching the web, "
            "managing git, and delegating subtasks.\n"
            "Always read before editing, show diffs before applying, and verify with tests or lint."
        )

    # -----------------------------------------------------------------------
    # core loop
    # -----------------------------------------------------------------------

    def abort(self) -> None:
        self._aborted = True

    async def run(self, user_input: str) -> str:
        async with self._lock:
            return await self._run_impl(user_input)

    async def _run_impl(self, user_input: str) -> str:
        self.conversation.add_user_message(user_input)
        self._aborted = False
        step = 0

        if self.config.proactive_scan:
            await self._proactive_scan(user_input)

        while step < self.config.max_steps:
            step += 1
            if self._aborted:
                return "[aborted]"

            messages = self.conversation.get_messages()
            response = await self._llm_call(messages)

            if not response.get("tool_calls"):
                final = response.get("content", "") or ""
                self.conversation.add_assistant_message(final)
                return final

            content = response.get("content", "") or ""
            tool_calls = response["tool_calls"]

            if content:
                self.conversation.add_assistant_message(content)

            for tc in tool_calls:
                name = tc["function"]["name"]
                raw = tc["function"]["arguments"]
                try:
                    import json
                    args = json.loads(raw) if isinstance(raw, str) else raw
                except json.JSONDecodeError:
                    args = {"raw": raw}

                if not isinstance(args, dict):
                    args = {"value": str(args)}

                if await self._confirm_action(name, args):
                    result = await self._execute_with_retry(name, args)
                else:
                    result = f"[user denied] {name} was not approved"

                self.conversation.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result[:10_000],
                })

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
                self.conversation.add_user_message(
                    f"[proactive scan of task: {user_input}]\n{content}"
                )
        except Exception as exc:
            logger.debug("Proactive scan failed: {}", exc)

    # -----------------------------------------------------------------------
    # confirmation
    # -----------------------------------------------------------------------

    async def _confirm_action(self, name: str, args: dict[str, Any]) -> bool:
        if not self.config.confirm_dangerous or not is_dangerous(name):
            return True
        if self.config.confirm_callback is not None:
            return await self.config.confirm_callback(name, args)
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
                diff = await self._diff_preview(name, args)
                if diff:
                    logger.info("Diff preview:\n{}", diff)

                result = await execute_tool(name, args)
                if isinstance(result, list):
                    result = "\n".join(str(r) for r in result[:200])
                return str(result)
            except Exception as exc:
                last_err = str(exc)
                logger.warning("Tool call attempt {}/{} failed: {}", attempt + 1, self.config.max_tool_retries, exc)
                delay = 2 ** attempt
                await asyncio.sleep(delay)
        return f"[error after {self.config.max_tool_retries} attempts]: {last_err}"

    # -----------------------------------------------------------------------
    # LLM call
    # -----------------------------------------------------------------------

    async def _llm_call(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.llm_provider is not None:
            result = await self.llm_provider(messages)
            return result if isinstance(result, dict) else {"content": str(result)}

        from ravencode.api.client import ask_stream

        tool_defs = get_tool_definitions()
        full = ""
        try:
            async with asyncio.timeout(self.config.llm_timeout):
                async for chunk in ask_stream(messages, tools=tool_defs):
                    full += chunk
        except TimeoutError:
            return {"content": "[error: LLM call timed out]", "tool_calls": []}

        return self._parse_response(full)

    def _parse_response(self, raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        if cleaned.startswith("{"):
            try:
                import json
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
        return {"content": raw, "tool_calls": []}

    # -----------------------------------------------------------------------
    # serialization
    # -----------------------------------------------------------------------

    def dump_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "config": self.config.__dict__,
            "conversation": self.conversation.messages,
        }

    @classmethod
    def load_state(cls, state: dict[str, Any], llm_provider: Any = None) -> Self:
        cfg = AgentConfig(**state.get("config", {}))
        conv = Conversation(messages=state.get("conversation", []))
        return cls(config=cfg, conversation=conv, llm_provider=llm_provider, name=state.get("name", "raven"))
