from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any


def _get_tool_registry():
    import importlib
    import sys
    _svc = Path(__file__).parent
    if str(_svc) not in sys.path:
        sys.path.insert(0, str(_svc))
    return importlib.import_module("tools").ToolRegistry


class AgentMode(StrEnum):
    BUILD = "build"
    PLAN = "plan"
    GENERAL = "general"


_MODE_DENIED: dict[AgentMode, list[str]] = {
    AgentMode.PLAN: ["write_file", "edit_file", "bash", "tool_delegate"],
    AgentMode.BUILD: [],
    AgentMode.GENERAL: [],
}

_MODE_TOOLS: dict[AgentMode, list[str]] = {
    AgentMode.BUILD: ["read_file", "write_file", "edit_file", "bash", "search", "glob", "grep", "tool_delegate"],
    AgentMode.PLAN: ["read_file", "search", "glob", "grep"],
    AgentMode.GENERAL: ["read_file", "search", "glob", "grep", "bash", "tool_delegate"],
}


class RavenCodeAgent:
    def __init__(self, mode: AgentMode = AgentMode.BUILD, workspace: str = ".") -> None:
        self.mode = mode
        self.workspace = Path(workspace).resolve()
        self.tools = _get_tool_registry()()
        self._context = None

    async def run(self, task: str, messages: list[dict[str, Any]] | None = None) -> str:
        if messages is None:
            messages = [
                {"role": "system", "content": self._build_system_prompt()},
            ]
        messages.append({"role": "user", "content": task})

        for _step in range(30):
            response_text = await self._llm_call(messages)
            if self._is_final(response_text):
                messages.append({"role": "assistant", "content": response_text})
                return response_text
            parsed = self._parse_response(response_text)
            if parsed and isinstance(parsed, dict) and "tool" in parsed:
                result = await self._execute_tool(parsed["tool"], parsed.get("args", {}))
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "tool", "content": result, "tool_call_id": parsed.get("tool", "")})
            else:
                messages.append({"role": "assistant", "content": response_text})
                return response_text
        return "[reached max steps]"

    async def _llm_call(self, messages: list[dict[str, Any]]) -> str:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "http://localhost:18888/api/raven",
                    json={"action": self.mode.value, "code": messages[-1].get("content", "")[:2000], "context": json.dumps(messages[:-1])[:500]},
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("response", "")
                return f"[llm error: {resp.status_code}]"
        except Exception as exc:
            return f"[llm error: {exc}]"

    def _is_final(self, text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith("[final:") or stripped.startswith("[error") or stripped.startswith("[done")

    def _parse_response(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        if text.startswith("[tool:") and "]" in text:
            tool_line, _, args_text = text.partition("]")
            tool_name = tool_line.replace("[tool:", "").strip()
            try:
                args = json.loads(args_text.strip())
            except json.JSONDecodeError:
                args = {"raw": args_text.strip()}
            return {"tool": tool_name, "args": args}
        if text.startswith("[tool "):
            parts = text.split(" ", 2)
            tool_name = parts[1] if len(parts) > 1 else ""
            args_raw = parts[2] if len(parts) > 2 else "{}"
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {"raw": args_raw}
            return {"tool": tool_name, "args": args}
        return None

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        denied = _MODE_DENIED.get(self.mode, [])
        if name in denied:
            return f"[denied] {name} is not allowed in {self.mode.value} mode"
        allowed = _MODE_TOOLS.get(self.mode, [])
        if name not in allowed:
            return f"[denied] {name} is not in allowed tools for {self.mode.value} mode"
        try:
            result = await self.tools.execute(name, **args)
            return str(result)[:10000]
        except Exception as exc:
            return f"[error] {name}: {exc}"

    def _build_system_prompt(self) -> str:
        allowed = ", ".join(_MODE_TOOLS.get(self.mode, []))
        denied = ", ".join(_MODE_DENIED.get(self.mode, [])) or "(none)"
        lines = [
            "You are RavenCode, an AI coding assistant.",
            f"Workspace: {self.workspace}",
            f"Mode: {self.mode.value}",
            "",
            f"Allowed tools: {allowed}",
            f"Denied tools: {denied}",
            "",
        ]
        if self.mode == AgentMode.PLAN:
            lines.append("IMPORTANT: You are in READ-ONLY mode. Analyze code, search, and plan but do NOT make changes.")
            lines.append("Do not use write_file, edit_file, or bash.")
        if self.mode == AgentMode.BUILD:
            lines.append("You have full access. Read before editing, show diffs before applying changes.")
        lines.append("")
        lines.append("To call a tool, respond with: [tool:tool_name] {\"arg\": \"value\"}")
        lines.append("To respond to the user, just write your response naturally.")
        return "\n".join(lines)
