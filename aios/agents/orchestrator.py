from typing import Any

from loguru import logger

from ravencode.agents.orchestrator import AgentType
from ravencode.agents.orchestrator import Orchestrator as RavenCodeOrchestrator


class Orchestrator:
    def __init__(self):
        self._inner = RavenCodeOrchestrator()

    async def dispatch(self, task: str, agent_type: AgentType) -> dict[str, Any]:
        try:
            result = await self._inner.dispatch(task, agent_type)
            return {"agent": result.agent, "success": result.success, "data": result.data, "error": result.error}
        except Exception as exc:
            logger.exception("Agent dispatch failed")
            return {"agent": agent_type.value, "success": False, "data": None, "error": str(exc)}
