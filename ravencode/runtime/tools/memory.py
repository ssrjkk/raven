from __future__ import annotations

import asyncio
import contextvars
from typing import Any


async def think(reasoning: str) -> str:
    return f"[thinking: {reasoning}]"




_task_depth: contextvars.ContextVar[int] = contextvars.ContextVar("_task_depth", default=0)


_MAX_TASK_DEPTH = 5



# A hung sub-agent must not wedge the parent loop forever.
_SUBTASK_TIMEOUT = 600



_AGENT_MEMORY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("_AGENT_MEMORY", default=None)



_MEMORY_STORE: contextvars.ContextVar[Any] = contextvars.ContextVar("_MEMORY_STORE", default=None)




def set_agent_memory(memory: dict[str, Any] | None) -> None:
    _AGENT_MEMORY.set(memory)




def set_agent_memory_store(store: Any) -> None:
    _MEMORY_STORE.set(store)




async def memory_remember(fact: str, key: str = "notes") -> str:
    """Persist a durable fact for future sessions (deduplicated, capped)."""
    store = _MEMORY_STORE.get()
    if store is None:
        return "[error] no memory store configured for this agent"
    fact = str(fact).strip()
    if not fact:
        return "[validation_error] fact must be a non-empty string"
    was_new = await store.push(key, fact)
    return "remembered" if was_new else "duplicate ignored (already known)"




async def memory_recall(key: str = "notes") -> str:
    """Recall previously persisted facts by key."""
    store = _MEMORY_STORE.get()
    if store is None:
        return "[error] no memory store configured for this agent"
    value = await store.get(str(key))
    if value is None:
        return f"(nothing remembered under '{key}')"
    if isinstance(value, list):
        if not value:
            return f"(nothing remembered under '{key}')"
        return "\n".join(f"- {item}" for item in value)
    return str(value)




async def task_delegate(description: str, context: str | None = None) -> str:
    depth = _task_depth.get()
    if depth >= _MAX_TASK_DEPTH:
        return f"[error] max task delegation depth ({_MAX_TASK_DEPTH}) exceeded"
    token = _task_depth.set(depth + 1)
    try:
        from ravencode.runtime.agent_core import AgentConfig, ReActAgent
        from ravencode.runtime.context import Conversation

        sub_prompt = _delegate_role_prompt(description)
        parent_memory = _AGENT_MEMORY.get()
        sub_memory_path: str | None = None
        if parent_memory:
            cfg = parent_memory.get("config")
            if isinstance(cfg, dict):
                sub_memory_path = cfg.get("memory_path") or None
        if context:
            sub_prompt += f"\nContext from parent:\n{context}"
        if parent_memory:
            sub_prompt += f"\nParent session context:\n{parent_memory}"
        prompt = f"{sub_prompt}\n\nTask: {description}"
        sub = ReActAgent(
            config=AgentConfig(max_steps=15, memory_path=sub_memory_path, priority="low"),
            conversation=Conversation(system_prompt=sub_prompt),
        )
        try:
            return await asyncio.wait_for(sub.run(prompt), timeout=_SUBTASK_TIMEOUT)
        except TimeoutError:
            return (
                f"[error] delegated task timed out after {_SUBTASK_TIMEOUT}s and was cancelled. "
                "Narrow the task and delegate again, or do it yourself in smaller steps."
            )
    finally:
        _task_depth.reset(token)




async def task_parallel(tasks: list[str], context: str | None = None) -> str:
    """Run several independent sub-tasks on concurrent sub-agents."""
    if not tasks or not isinstance(tasks, list):
        return "[error] tasks must be a non-empty list of task descriptions"
    tasks = [str(t).strip() for t in tasks if str(t).strip()][:6]
    if not tasks:
        return "[error] tasks must contain at least one non-empty description"
    depth = _task_depth.get()
    if depth >= _MAX_TASK_DEPTH:
        return f"[error] max task delegation depth ({_MAX_TASK_DEPTH}) exceeded"
    token = _task_depth.set(depth + 1)
    try:
        from ravencode.agents.orchestrator import Orchestrator

        results = await asyncio.wait_for(
            Orchestrator.delegate_parallel(tasks, context=context),
            timeout=_SUBTASK_TIMEOUT,
        )
        parts = []
        for task, result in zip(tasks, results, strict=True):
            parts.append(f"### Sub-task: {task}\n{result}")
        return "\n\n".join(parts)
    except TimeoutError:
        return (
            f"[error] parallel delegation timed out after {_SUBTASK_TIMEOUT}s. "
            "Delegate fewer tasks or split them further."
        )
    finally:
        _task_depth.reset(token)




def _delegate_role_prompt(description: str) -> str:
    from ravencode.core.prompts import CODER, DEBUGGER, DELEGATE, PLANNER, VERIFIER, get_prompt

    task_lower = description.lower()
    if any(w in task_lower for w in ("debug", "error", "crash", "fix", "bug", "failing", "traceback", "exception")):
        return get_prompt(DEBUGGER)
    if any(
        w in task_lower
        for w in ("review", "check", "lint", "quality", "audit", "verify", "validate", "test", "confirm")
    ):
        return get_prompt(VERIFIER)
    if any(w in task_lower for w in ("plan", "break down", "decompose", "roadmap", "milestone", "steps")):
        return get_prompt(PLANNER)
    if any(w in task_lower for w in ("write", "implement", "create", "code", "refactor", "add feature", "develop")):
        return get_prompt(CODER)
    return get_prompt(DELEGATE)
