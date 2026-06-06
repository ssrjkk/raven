from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter


class AIOSAdapter:
    """Boundary adapter isolating raven/cli from aios/ and ravencode/ modules.

    All imports from aios/ and ravencode/ are lazy — loaded only when the
    corresponding method is called. This prevents cross-layer import violations
    at module load time and keeps the layer boundary enforced at the file level.
    """

    # ── AI-OS-MVP Bridge (aios.api.bridge) ─────────────────────────

    def get_bridge_router(self) -> APIRouter:
        from aios.api.bridge import router

        return router

    # ── AI-OS-MVP Agent (aios.agents.orchestrator) ─────────────────

    async def run_agent(self, task: str, agent: str) -> dict[str, Any]:
        from aios.agents.orchestrator import AgentType, Orchestrator  # type: ignore[attr-defined]

        orch = Orchestrator()
        agent_type = AgentType(agent) if agent in [e.value for e in AgentType] else AgentType.AUTONOMOUS
        return await orch.dispatch(task, agent_type)

    # ── AI-OS-MVP Runtime (aios.runtime.adapter) ───────────────────

    async def run_command(self, cmd: str) -> str:
        from aios.runtime.adapter import RuntimeAdapter

        return await RuntimeAdapter.run_command(cmd)

    # ── RavenCode Client (ravencode.api.client) ────────────────────

    async def ask(self, prompt: str, task: str = "code") -> Any:
        from ravencode.api.client import AIOSClient

        client = AIOSClient()
        return await client.ask(prompt, task=task)

    # ── RavenCode Agent (ravencode.agents.orchestrator) ───────────

    async def run_agent_task(self, task: str, agent: str) -> Any:
        from ravencode.agents.orchestrator import AgentType, Orchestrator

        orch = Orchestrator()
        result = await orch.dispatch(task, AgentType(agent))
        return result

    # ── RavenCode Shell (ravencode.runtime.shell) ──────────────────

    async def run_shell(self, cmd: str) -> str:
        from ravencode.runtime.shell import ShellExecutor

        executor = ShellExecutor()
        return await executor.run(cmd)


_adapter: AIOSAdapter | None = None


def get_aios_adapter() -> AIOSAdapter:
    global _adapter
    if _adapter is None:
        _adapter = AIOSAdapter()
    return _adapter
