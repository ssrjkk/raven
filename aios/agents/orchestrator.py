"""
Agent Orchestrator — bridges Raven's Python agents with the
TypeScript multi-agent system (planner, coder, debugger, loop).

Dispatches tasks to the appropriate agent subsystem based on task type.
"""

from enum import Enum
from typing import Any


class AgentType(Enum):
    PLANNER = "planner"
    CODER = "coder"
    DEBUGGER = "debugger"
    AUTONOMOUS = "autonomous"


class Orchestrator:
    """Routes tasks to the right agent backend (Python or TS via subprocess)."""

    def __init__(self):
        self.memory: list[dict[str, Any]] = []

    async def dispatch(self, task: str, agent_type: AgentType) -> dict[str, Any]:
        """Dispatch a task to the appropriate agent."""
        if agent_type == AgentType.PLANNER:
            return await self._run_planner(task)
        elif agent_type == AgentType.CODER:
            return await self._run_coder(task)
        elif agent_type == AgentType.DEBUGGER:
            return await self._run_debugger(task)
        elif agent_type == AgentType.AUTONOMOUS:
            return await self._run_autonomous_loop(task)
        return {"error": f"Unknown agent type: {agent_type}"}

    async def _run_planner(self, task: str) -> dict[str, Any]:
        from raven.core.task_engine.planner import TaskPlanner
        planner = TaskPlanner()
        plan = await planner.plan(task)
        self.memory.append({"type": "plan", "task": task, "plan": plan})
        return {"agent": "planner", "plan": plan}

    async def _run_coder(self, task: str) -> dict[str, Any]:
        from raven.core.coder.session import CodingSessionManager
        coder = CodingSessionManager()
        result = await coder.execute(task)
        self.memory.append({"type": "code", "task": task, "result": result})
        return {"agent": "coder", "result": result}

    async def _run_debugger(self, task: str) -> dict[str, Any]:
        from raven.core.coder.review import CodeReviewer
        reviewer = CodeReviewer()
        review = await reviewer.review(task)
        self.memory.append({"type": "debug", "task": task, "review": review})
        return {"agent": "debugger", "issues": review}

    async def _run_autonomous_loop(self, task: str) -> dict[str, Any]:
        max_steps = 25
        results = []

        for step in range(max_steps):
            plan = await self._run_planner(f"{task} (step {step + 1})")
            results.append(plan)

            if step > 0 and results[-1] == results[-2]:
                break

        return {"agent": "autonomous", "steps": len(results), "completed": True}
