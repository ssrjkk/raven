from __future__ import annotations
import json
from typing import AsyncIterator, Any
from loguru import logger
from raven.core.db import Database
from raven.core.llm import LLMRouter, ToolCall, LLMResponse
from raven.core.models import Message, Session, PluginTool


class AgentConfig:
    def __init__(
        self,
        agent_id: str = "default",
        system_prompt: str | None = None,
        model: str | None = None,
        max_tool_rounds: int = 10,
        max_history: int = 50,
        use_memory: bool = True,
    ):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.max_history = max_history
        self.use_memory = use_memory


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
    ):
        self.session = session
        self.tools = tools
        self.db = db
        self.llm = llm
        self.config = config or AgentConfig()
        self._tool_map: dict[str, PluginTool] = {t.name: t for t in tools}

    def _build_system_prompt(self) -> str:
        base = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        if self.session.system_prompt:
            base = self.session.system_prompt + "\n\n" + base
        return base

    def _tool_schemas(self) -> list[dict]:
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

    async def _load_history(self) -> list[dict]:
        msgs = await self.db.get_session_messages(self.session.id, limit=self.config.max_history)
        history: list[dict] = []
        for m in msgs:
            entry: dict = {"role": m.role, "content": m.content}
            history.append(entry)
        return history

    async def _compress(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= 6:
            return messages
        conversation = "\n".join(
            f"{m['role']}: {(m.get('content') or '')[:200]}"
            for m in messages[:-4]
        )
        prompt = [
            {"role": "system", "content": "Summarize the key points of this conversation concisely in 2-3 sentences."},
            {"role": "user", "content": f"Summarize:\n{conversation}"},
        ]
        try:
            resp = await self.llm.complete(prompt)
            summary = (resp.content or "")[:500]
            if summary.strip():
                compressed = [{"role": "system", "content": f"[Context summary: {summary}]"}]
                compressed.extend(messages[-4:])
                return compressed
        except Exception as e:
            logger.warning("Compression failed: {}", e)
        return messages[-8:]

    async def _auto_memory(self, user_text: str, response_text: str):
        if not self.config.use_memory:
            return
        recall_tool = self._tool_map.get("recall")
        remember_tool = self._tool_map.get("remember")
        if recall_tool and user_text.strip():
            try:
                await recall_tool.handler(query=user_text, limit=3)
            except Exception as e:
                logger.debug("Auto-recall: {}", e)
        if remember_tool and response_text.strip():
            try:
                await remember_tool.handler(content=f"User: {user_text[:300]}")
            except Exception as e:
                logger.debug("Auto-remember: {}", e)

    async def _get_recall_context(self, query: str) -> str | None:
        recall_tool = self._tool_map.get("recall")
        if not recall_tool:
            return None
        try:
            result = await recall_tool.handler(query=query, limit=5)
            text = str(result) if result else ""
            return text if text.strip() and "No relevant memories" not in text else None
        except Exception as e:
            logger.debug("Recall error: {}", e)
            return None

    async def run(
        self,
        user_message: str,
        recall_context: str | None = None,
    ) -> AsyncIterator[str]:
        if recall_context is None:
            recall_context = await self._get_recall_context(user_message)

        messages: list[dict] = [{"role": "system", "content": self._build_system_prompt()}]
        if recall_context:
            messages.append({"role": "system", "content": f"Relevant memories:\n{recall_context}"})

        history = await self._load_history()
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        if len(messages) > self.config.max_history + 3:
            messages = await self._compress(messages)
            messages.append({"role": "user", "content": user_message})

        schemas = self._tool_schemas() if self.tools else None
        full_content = ""
        final_content = ""

        for round_i in range(self.config.max_tool_rounds):
            resp = await self.llm.complete(messages, tools=schemas)
            content = resp.content or ""
            full_content += content

            if resp.tool_calls:
                messages.append({"role": "assistant", "content": content, "tool_calls": [tc.to_dict() for tc in resp.tool_calls]})
                for tc in resp.tool_calls:
                    tool_result = await self._execute_tool(tc)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_result)})
                    yield f"[{tc.name} → ok]\n"
                    full_content += f"\n[{tc.name} → ok]\n"
                continue

            if content:
                final_content = content
            break
        else:
            final_content = full_content or "I apologize, but I couldn't complete that request."

        async for token in self.llm.complete_stream(messages):
            final_content += token
            yield token

        user_msg = Message(session_id=self.session.id, channel=self.session.channel, role="user", content=user_message)
        assistant_msg = Message(session_id=self.session.id, channel=self.session.channel, role="assistant", content=final_content)
        await self.db.save_message(user_msg)
        await self.db.save_message(assistant_msg)

        await self._auto_memory(user_message, final_content)

    async def _execute_tool(self, tc: ToolCall) -> dict:
        tool = self._tool_map.get(tc.name)
        if not tool:
            logger.warning("Unknown tool: {}", tc.name)
            return {"error": f"Unknown tool: {tc.name}"}
        try:
            logger.info("Tool call: {} args={}", tc.name, tc.arguments)
            result = await tool.handler(**tc.arguments)
            return {"result": str(result)[:4000]}
        except Exception as e:
            logger.error("Tool {} error: {}", tc.name, e)
            return {"error": str(e)[:500]}

    async def simple_complete(self, messages: list[dict]) -> AsyncIterator[str]:
        async for token in self.llm.complete_stream(messages):
            yield token
