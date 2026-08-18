from __future__ import annotations

import time
from typing import Any

from loguru import logger

from raven.core._json import json
from raven.core.llm import LLMRouter
from raven.core.task_engine.models import Task, TaskStep
from raven.core.task_engine.tool_registry import ToolRegistry

PLANNER_PROMPT = """\
You are a task planner for the Raven AI assistant.
Given a user's goal and a list of available tools, decompose the goal into a sequence of steps.
Each step must use ONE tool from the available list.

Goal: {goal}

Available tools:
{tools_list}

Rules:
- Break the goal into the smallest reasonable steps
- Each step must map to exactly one tool
- Steps should run in sequence (each depends on the previous)
- Keep descriptions concise (under 80 chars)
- Return ONLY valid JSON, no explanation

Output format:
```json
{{
  "summary": "One-line plan summary",
  "steps": [
    {{
      "description": "what this step does",
      "tool": "tool_name",
      "params": {{ "param1": "value1" }}
    }}
  ]
}}
```"""


class TaskPlanner:
    def __init__(self, tools: ToolRegistry):
        self._tools = tools

    async def plan(self, goal: str, llm: LLMRouter, task_id: str = "", user_id: str = "", channel: str = "") -> Task:
        prompt = self._build_prompt(goal)
        messages = [{"role": "user", "content": prompt}]
        response = ""
        async for token in llm.complete_stream(messages):
            response += token

        plan_data = self._parse_response(response)
        if not isinstance(plan_data, dict):
            plan_data = {"summary": response[:100], "steps": []}

        steps: list[TaskStep] = []
        for i, s in enumerate(plan_data.get("steps") or []):
            if not isinstance(s, dict):
                continue
            params = s.get("params")
            if not isinstance(params, dict):
                params = {}
            steps.append(
                TaskStep(
                    task_id=task_id,
                    order=i,
                    description=s.get("description", ""),
                    tool=s.get("tool", ""),
                    params=params,
                )
            )

        return Task(
            id=task_id,
            user_id=user_id,
            channel=channel,
            goal=goal,
            plan_summary=plan_data.get("summary", goal[:80]),
            steps=steps,
            created_at=time.time(),
            updated_at=time.time(),
        )

    def _build_prompt(self, goal: str) -> str:
        tools_list = "\n".join(
            f"- {t.name}: {t.description} (params: {json.dumps(t.parameters)})" for t in self._tools.list()
        )
        return PLANNER_PROMPT.format(tools_list=tools_list, goal=goal)

    def _parse_response(self, text: str) -> dict[str, Any]:
        try:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
        except (ValueError, json.JSONDecodeError):
            logger.warning("Planner: failed to parse LLM response, returning default")
            data = None
        if not isinstance(data, dict):
            logger.warning("Planner: LLM response is not a JSON object, returning default")
            return {
                "summary": text[:100],
                "steps": [],
            }
        return data
