from __future__ import annotations

from raven.core.ab_testing import _engine
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


async def ab_create(name: str, description: str, variants_json: str, metric_name: str = "conversion") -> str:
    import json
    try:
        variants = json.loads(variants_json)
    except json.JSONDecodeError as e:
        return f"[error] Invalid variants JSON: {e}"
    if len(variants) < 2:
        return "[error] At least 2 variants required"
    exp = _engine.create_experiment(name, description, variants, metric_name)
    return (
        f"Experiment created [id={exp.id}]:\n"
        f"- Name: {exp.name}\n"
        f"- Variants: {', '.join(v['name'] for v in variants)}\n"
        f"- Metric: {exp.metric_name}\n"
        f"Use ab_start {exp.id} to begin."
    )


async def ab_list() -> str:
    experiments = _engine.list_experiments()
    if not experiments:
        return "[info] No experiments yet."
    lines = [f"Experiments ({len(experiments)}):"]
    for e in experiments:
        lines.append(f"  [{e.id}] {e.name} — {e.status} ({len(e.variants)} variants)")
    return "\n".join(lines)


async def ab_get(experiment_id: str) -> str:
    exp = _engine.get_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return (
        f"Experiment: {exp.name}\n"
        f"- ID: {exp.id}\n"
        f"- Description: {exp.description}\n"
        f"- Status: {exp.status}\n"
        f"- Metric: {exp.metric_name}\n"
        f"- Variants: {', '.join(f'{v.name} ({v.weight*100:.0f}%)' for v in exp.variants)}\n"
        f"- Created: {exp.created_at}"
    )


async def ab_start(experiment_id: str) -> str:
    exp = _engine.start_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{exp.name}' started."


async def ab_pause(experiment_id: str) -> str:
    exp = _engine.pause_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{exp.name}' paused."


async def ab_complete(experiment_id: str) -> str:
    exp = _engine.complete_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{exp.name}' completed."


async def ab_delete(experiment_id: str) -> str:
    ok = _engine.delete_experiment(experiment_id)
    if not ok:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{experiment_id}' deleted."


async def ab_assign(experiment_id: str, user_id: str = "") -> str:
    variant = _engine.assign_variant(experiment_id, user_id)
    if variant is None:
        return f"[error] Experiment '{experiment_id}' not found or not running."
    return variant


async def ab_record(experiment_id: str, variant: str, metric_name: str = "conversion", value: float = 1.0, user_id: str = "") -> str:
    _engine.record_event(experiment_id, variant, metric_name, value, user_id)
    return f"Event recorded: {experiment_id}/{variant}/{metric_name}={value}"


async def ab_results(experiment_id: str) -> str:
    results = _engine.get_results(experiment_id)
    if not results:
        return f"[error] Experiment '{experiment_id}' not found."
    lines = [
        f"Results: {results['name']} ({results['status']})",
        f"Metric: {results['metric']}",
        f"Total events: {results['total_events']}",
    ]
    if results["significant"]:
        lines.append(f"Statistically significant! (p={results['significance']:.4f})")
    else:
        lines.append(f"Not yet significant (p={results['significance']:.4f}, need >=0.95)")
    for v in results["variants"]:
        lines.append(f"  [{v['name']}] events={v['events']}, avg={v['avg_value']}, lift={v['lift']}%")
    return "\n".join(lines)


def register_ab_testing_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="ab_create",
        description="Create an A/B test experiment with variants (JSON array)",
        parameters={
            "name": {"type": "string", "description": "Experiment name", "required": True},
            "description": {"type": "string", "description": "Experiment description", "required": True},
            "variants_json": {"type": "string", "description": "JSON array of variants [{\"name\":\"A\",\"weight\":0.5,\"config\":{}},...]", "required": True},
            "metric_name": {"type": "string", "description": "Primary metric name (default conversion)", "required": False},
        },
        handler=ab_create,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_list",
        description="List all A/B experiments",
        parameters={},
        handler=ab_list,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_get",
        description="Get experiment details",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=ab_get,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_start",
        description="Start an experiment",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=ab_start,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_pause",
        description="Pause an experiment",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=ab_pause,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_complete",
        description="Complete an experiment",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=ab_complete,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_delete",
        description="Delete an experiment",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=ab_delete,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_assign",
        description="Assign a user to a variant for an experiment",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            "user_id": {"type": "string", "description": "User ID (optional, deterministic)", "required": False},
        },
        handler=ab_assign,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_record",
        description="Record an event/metric for an experiment variant",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            "variant": {"type": "string", "description": "Variant name", "required": True},
            "metric_name": {"type": "string", "description": "Metric name (default conversion)", "required": False},
            "value": {"type": "number", "description": "Metric value (default 1.0)", "required": False},
            "user_id": {"type": "string", "description": "User ID (optional)", "required": False},
        },
        handler=ab_record,
        category="ab_testing",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="ab_results",
        description="Get experiment results with statistical significance",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=ab_results,
        category="ab_testing",
        timeout=10,
    ))
