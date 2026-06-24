from __future__ import annotations

from loguru import logger

from raven.core.llm import LLMRouter
from ravencode.runtime.context import Conversation
from ravencode.runtime.tools import execute_tool, get_tool_definitions


class ReActAgent:
    def __init__(
        self,
        llm: LLMRouter | None = None,
        model: str | None = None,
        max_steps: int = 30,
        system_prompt: str | None = None,
    ):
        self._llm = llm or LLMRouter()
        self._model = model
        self._max_steps = max_steps
        self._tool_defs = get_tool_definitions()
        self._context = Conversation(system_prompt=system_prompt)
        self._context.set_tools(self._tool_defs)
        self._on_token: list[callable] = []

    def on_token(self, cb: callable) -> None:
        self._on_token.append(cb)

    async def _emit_token(self, token: str) -> None:
        for cb in self._on_token:
            if callable(cb):
                cb(token)

    async def run(self, task: str, stream: bool = False) -> str:
        self._context.add_user_message(task)
        full_response = ""
        for step in range(1, self._max_steps + 1):
            logger.debug("Agent step {}/{}", step, self._max_steps)
            self._context.trim_if_needed()
            messages = self._context.get_messages()
            response = await self._llm.complete(messages, model=self._model, tools=self._tool_defs)

            if response.tool_calls:
                content_so_far = response.content or ""
                if content_so_far:
                    full_response += content_so_far
                    if stream:
                        await self._emit_token(content_so_far)
                self._context.add_assistant_message(response.content, response.tool_calls)
                for tc in response.tool_calls:
                    logger.info("Tool call: {} {}", tc.name, tc.arguments)
                    if stream:
                        await self._emit_token(f"\n\n**Tool: {tc.name}**\n\n```\n")
                    result = await execute_tool(tc.name, tc.arguments)
                    self._context.add_tool_result(tc.id, result)
                    if stream:
                        await self._emit_token(result[:500])
                        await self._emit_token("\n```\n")
            elif response.content:
                full_response += response.content
                if stream:
                    await self._emit_token(response.content)
                self._context.add_assistant_message(response.content)
                return full_response
            else:
                self._context.add_assistant_message("(no response)")
                return full_response or "(no output)"

        full_response += "\n\n[reached max steps]"
        return full_response

    async def run_stream(self, task: str):
        class Collector:
            def __init__(self):
                self.full = ""
            def write(self, token: str):
                self.full += token

        collector = Collector()
        self.on_token(collector.write)
        await self.run(task, stream=True)
        return collector.full

    def reset(self) -> None:
        self._context = Conversation()
        self._context.set_tools(self._tool_defs)
        self._on_token = []
