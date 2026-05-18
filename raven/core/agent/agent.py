from __future__ import annotations

import json
from typing import Any, AsyncIterator

from loguru import logger

from raven.core.db import Database
from raven.core.llm import LLMRouter, ToolCall
from raven.core.models import Message, PluginTool, Session


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
    ):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.model = model
        self.max_tool_rounds = max_tool_rounds
        self.max_history = 0 if stateless else max_history
        self.use_memory = False if stateless else use_memory
        self.stateless = stateless
        self.workspace = workspace


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
        self._tool_map: dict[str, PluginTool] = {t.name: t for t in tools}
        self._tool_policy = tool_policy or self._init_tool_policy()

    def _init_tool_policy(self):
        from raven.core.config import settings, _DEFAULT_TOOLS_DENY
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

    def _build_system_prompt(self) -> str:
        base = self.config.system_prompt or DEFAULT_SYSTEM_PROMPT
        if self.session.system_prompt:
            base = self.session.system_prompt + "\n\n" + base
        workspace = self.config.workspace
        if workspace:
            from pathlib import Path
            ws = Path(workspace)
            for fname in ("SOUL.md", "AGENTS.md", "TOOLS.md"):
                fp = ws / fname
                if fp.exists():
                    content = fp.read_text(encoding="utf-8").strip()
                    if content:
                        base += f"\n\n---\n[{fname}]\n{content}"
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

    async def run(
        self,
        user_message: str,
        recall_context: str | None = None,
    ) -> AsyncIterator[str]:
        if not self.config.stateless:
            if recall_context is None:
                recall_context = await self._get_recall_context(user_message)

        messages: list[dict] = [{"role": "system", "content": self._build_system_prompt()}]
        if recall_context:
            messages.append({"role": "system", "content": f"Relevant memories:\n{recall_context}"})

        if not self.config.stateless:
            history = await self._load_history()
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        if not self.config.stateless and len(messages) > self.config.max_history + 3:
            messages = await self._compress(messages)

        schemas = self._tool_schemas() if self.tools else None
        tool_used = False
        final_content = ""

        for round_i in range(self.config.max_tool_rounds):
            resp = await self.llm.complete(messages, tools=schemas)
            content = resp.content or ""

            if resp.tool_calls:
                tool_used = True
                messages.append({"role": "assistant", "content": content, "tool_calls": [tc.to_dict() for tc in resp.tool_calls]})
                for tc in resp.tool_calls:
                    tool_result = await self._execute_tool(tc)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tool_result)})
                    yield f"[{tc.name} → ok]\n"
                continue

            final_content = content
            break
        else:
            final_content = "I apologize, but I couldn't complete that request."

        if final_content:
            yield final_content
        elif tool_used:
            async for token in self.llm.complete_stream(messages):
                final_content += token
                yield token

        if not self.config.stateless:
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
        allowed = self._tool_policy.is_tool_allowed(tc.name)
        if not allowed:
            logger.warning("Tool '{}' denied by policy", tc.name)
            return {"error": f"Tool '{tc.name}' is denied by security policy"}
        path_ok = self._tool_policy.check_path(str(tc.arguments) if tc.arguments else "")
        if not path_ok:
            return {"error": "Path outside workspace root — denied by security policy"}
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
