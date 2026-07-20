from __future__ import annotations

from raven.core.cost_management import _cost
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


def cost_record(model: str, input_tokens: int, output_tokens: int, user_id: str = "", channel: str = "", session_id: str = "") -> str:
    rec = _cost.record_usage(model, input_tokens, output_tokens, user_id, channel, session_id)
    return f"Usage recorded: {rec.model} ({rec.input_tokens} in / {rec.output_tokens} out) — ${rec.cost:.6f}"


def cost_summary(hours: int = 24) -> str:
    summary = _cost.get_usage_summary(hours)
    lines = [
        f"Cost Summary (past {hours}h):",
        f"  Total cost: ${summary['total_cost']:.4f}",
        f"  Total input tokens: {summary['total_input_tokens']:,}",
        f"  Total output tokens: {summary['total_output_tokens']:,}",
        f"  Total LLM calls: {summary['total_calls']}",
        f"  Daily cost: ${summary['daily_cost']:.4f}",
        f"  Monthly cost: ${summary['monthly_cost']:.4f}",
    ]
    if summary["by_model"]:
        lines.append("  By model:")
        for model, data in summary["by_model"].items():
            lines.append(f"    {model}: ${data['cost']:.4f} ({data['calls']} calls, {data['input_tokens']} in / {data['output_tokens']} out)")
    return "\n".join(lines)


def cost_pricing() -> str:
    pricing = _cost.get_model_pricing()
    lines = ["Model Pricing ($ per 1K tokens):"]
    for model, rates in sorted(pricing.items()):
        lines.append(f"  {model}: ${rates['input_per_1k']:.5f} in / ${rates['output_per_1k']:.5f} out")
    return "\n".join(lines)


def cost_set_pricing(model: str, input_per_1k: float, output_per_1k: float) -> str:
    _cost.set_model_pricing(model, input_per_1k, output_per_1k)
    return f"Pricing set for '{model}': ${input_per_1k:.5f} in / ${output_per_1k:.5f} out"


def cost_budget_create(name: str, daily_limit: float, monthly_limit: float) -> str:
    budget = _cost.set_budget(name, daily_limit, monthly_limit)
    return f"Budget created [id={budget.id}]: {budget.name} (daily=${daily_limit:.2f}, monthly=${monthly_limit:.2f})"


def cost_budget_list() -> str:
    budgets = _cost.get_budgets()
    if not budgets:
        return "[info] No budgets configured."
    lines = ["Budgets:"]
    for b in budgets:
        daily_pct = (b.current_daily / b.daily_limit * 100) if b.daily_limit > 0 else 0
        monthly_pct = (b.current_monthly / b.monthly_limit * 100) if b.monthly_limit > 0 else 0
        lines.append(f"  [{b.id}] {b.name}: daily ${b.current_daily:.2f}/{b.daily_limit:.2f} ({daily_pct:.0f}%), monthly ${b.current_monthly:.2f}/{b.monthly_limit:.2f} ({monthly_pct:.0f}%)")
    exceeded = _cost.is_budget_exceeded()
    if exceeded:
        lines.append("  ⚠ BUDGET EXCEEDED!")
    return "\n".join(lines)


def cost_budget_delete(budget_id: str) -> str:
    ok = _cost.delete_budget(budget_id)
    if not ok:
        return f"[error] Budget '{budget_id}' not found."
    return "Budget deleted."


def cost_check() -> str:
    exceeded = _cost.is_budget_exceeded()
    daily = _cost.get_daily_cost()
    monthly = _cost.get_monthly_cost()
    total = _cost.get_total_cost()
    return (
        f"Cost Check\n"
        f"  Total: ${total:.4f}\n"
        f"  Daily: ${daily:.4f}\n"
        f"  Monthly: ${monthly:.4f}\n"
        f"  Budget exceeded: {'YES' if exceeded else 'No'}"
    )


def register_cost_management_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="cost_record",
        description="Record LLM token usage and calculate cost",
        parameters={
            "model": {"type": "string", "description": "Model name", "required": True},
            "input_tokens": {"type": "number", "description": "Input token count", "required": True},
            "output_tokens": {"type": "number", "description": "Output token count", "required": True},
            "user_id": {"type": "string", "description": "User ID (optional)", "required": False},
            "channel": {"type": "string", "description": "Channel name (optional)", "required": False},
            "session_id": {"type": "string", "description": "Session ID (optional)", "required": False},
        },
        handler=cost_record,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_summary",
        description="Get cost summary for recent usage",
        parameters={
            "hours": {"type": "number", "description": "Hours of history (default 24)", "required": False},
        },
        handler=cost_summary,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_pricing",
        description="List all model pricing rates",
        parameters={},
        handler=cost_pricing,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_set_pricing",
        description="Set or update pricing for a model",
        parameters={
            "model": {"type": "string", "description": "Model name", "required": True},
            "input_per_1k": {"type": "number", "description": "Input cost per 1K tokens", "required": True},
            "output_per_1k": {"type": "number", "description": "Output cost per 1K tokens", "required": True},
        },
        handler=cost_set_pricing,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_budget_create",
        description="Create a budget with daily and monthly limits",
        parameters={
            "name": {"type": "string", "description": "Budget name", "required": True},
            "daily_limit": {"type": "number", "description": "Daily spending limit in USD", "required": True},
            "monthly_limit": {"type": "number", "description": "Monthly spending limit in USD", "required": True},
        },
        handler=cost_budget_create,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_budget_list",
        description="List all budgets and current usage",
        parameters={},
        handler=cost_budget_list,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_budget_delete",
        description="Delete a budget",
        parameters={
            "budget_id": {"type": "string", "description": "Budget ID", "required": True},
        },
        handler=cost_budget_delete,
        category="cost",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="cost_check",
        description="Check current costs and budget status",
        parameters={},
        handler=cost_check,
        category="cost",
        timeout=10,
    ))
