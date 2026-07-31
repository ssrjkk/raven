from __future__ import annotations

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def delegate_task(profile: str, task: str) -> str:
    from raven.core.agents.orchestrator import AgentOrchestrator
    from raven.core.agents.profiles import PROFILES
    from raven.core.llm.router import LLMRouter
    from raven.tools.register_all import create_tool_registry

    available = ", ".join(sorted(PROFILES))
    if profile not in PROFILES:
        return f"Unknown profile '{profile}'. Available: {available}"

    llm = LLMRouter()
    tools = create_tool_registry()
    orch = AgentOrchestrator(llm=llm, tool_registry=tools)
    result = await orch.execute(query=task, profile_override=profile)
    return f"**{profile}** result: {result.content[:2000]}"


async def list_profiles() -> str:
    from raven.core.agents.profiles import PROFILES, resolve_profile

    lines: list[str] = []
    for name in sorted(PROFILES):
        p = resolve_profile(name)
        lines.append(f"- **{p.display_name}** (`{name}`): {p.role}")
    return "\n".join(lines)


def register_delegation_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="delegate_task",
            description="Delegate a task to a specific agent profile (architect, coder, reviewer, debugger, qa, researcher, security, planner)",
            parameters={
                "profile": {"type": "string", "description": "Agent profile name", "required": True},
                "task": {"type": "string", "description": "Task description", "required": True},
            },
            handler=delegate_task,
            category="ai",
            timeout=300,
        )
    )
    registry.register(
        ToolSpec(
            name="list_profiles",
            description="List all available agent delegation profiles",
            parameters={},
            handler=list_profiles,
            category="ai",
            timeout=10,
        )
    )
