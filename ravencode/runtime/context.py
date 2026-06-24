from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT_TEMPLATE = """You are RavenCode, an autonomous AI engineering assistant with full access to tools.

## Available tools
{tool_descriptions}

## How to use tools
The system will automatically detect when you want to use a tool and execute it.
Just respond naturally — when you say "I'll read the file" or "let me search for X",
the system handles it. You can also explicitly request a tool.

## Guidelines
- Think step by step before acting
- Use read/grep/glob to explore the codebase before making changes
- Use edit for precise changes, write for new files
- After completing the task, provide a clear summary of what was done
- If you encounter errors, diagnose them using available tools
- Use web_search and web_fetch to get current information when needed
"""


class Conversation:
    def __init__(self, system_prompt: str | None = None):
        self.messages: list[dict[str, Any]] = []
        self.max_tokens = 128_000
        self._tool_defs: list[dict[str, Any]] = []
        if system_prompt:
            self.system_prompt = system_prompt
        else:
            self.system_prompt = SYSTEM_PROMPT_TEMPLATE

    def set_tools(self, tool_defs: list[dict[str, Any]]) -> None:
        self._tool_defs = tool_defs
        descriptions = []
        for td in tool_defs:
            func = td.get("function", td)
            params = func.get("parameters", {}).get("properties", {})
            param_str = ", ".join(params.keys()) if params else "(no params)"
            descriptions.append(f"- {func['name']}({param_str}): {func.get('description', '')[:100]}")
        tool_block = "\n".join(descriptions)
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{tool_descriptions}", tool_block)

    def get_messages(self) -> list[dict[str, Any]]:
        return [{"role": "system", "content": self.system_prompt}, *self.messages]

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str, tool_calls: list[Any] | None = None) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, result: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })

    def trim_if_needed(self, reserve: int = 4_000) -> None:
        if len(self.messages) <= 2:
            return
        estimated = sum(len(json.dumps(m)) for m in self.messages)
        if estimated < self.max_tokens - reserve:
            return
        while len(self.messages) > 2 and estimated >= self.max_tokens - reserve:
            removed = self.messages.pop(1)
            estimated -= len(json.dumps(removed))

    @property
    def message_count(self) -> int:
        return len(self.messages)
