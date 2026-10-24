from __future__ import annotations

from raven.core.ab_testing import _engine
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec


def ab_create(
    name: str, description: str, variants_json: str, metric_name: str = "conversion", metric_type: str = "rate"
) -> str:
    import json

    try:
        variants = json.loads(variants_json)
    except json.JSONDecodeError as e:
        return f"[error] Invalid variants JSON: {e}"
    if not isinstance(variants, list):
        return "[error] variants must be a JSON array"
    if len(variants) < 2:
        return "[error] At least 2 variants required"
    try:
        exp = _engine.create_experiment(name, description, variants, metric_name, metric_type)
    except ValueError as e:
        return f"[error] {e}"
    control = exp.control.name
    return (
        f"Experiment created [id={exp.id}]:\n"
        f"- Name: {exp.name}\n"
        f"- Variants: {', '.join(f'{v.name} (weight {v.weight:g})' for v in exp.variants)}\n"
        f"- Control: {control}\n"
        f"- Metric: {exp.metric_name} ({exp.metric_type})\n"
        f"Use ab_start {exp.id} to begin."
    )


def ab_list() -> str:
    experiments = _engine.list_experiments()
    if not experiments:
        return "[info] No experiments yet."
    lines = [f"Experiments ({len(experiments)}):"]
    for e in experiments:
        lines.append(f"  [{e.id}] {e.name} — {e.status} ({len(e.variants)} variants)")
    return "\n".join(lines)


def ab_get(experiment_id: str) -> str:
    exp = _engine.get_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    rendered = ", ".join(
        f"{v.name} (weight {v.weight:g})" + (" [control]" if v.is_control else "") for v in exp.variants
    )
    return (
        f"Experiment: {exp.name}\n"
        f"- ID: {exp.id}\n"
        f"- Description: {exp.description}\n"
        f"- Status: {exp.status}\n"
        f"- Metric: {exp.metric_name} ({exp.metric_type})\n"
        f"- Variants: {rendered}\n"
        f"- Created: {exp.created_at}"
    )


def ab_start(experiment_id: str) -> str:
    exp = _engine.start_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{exp.name}' started."


def ab_pause(experiment_id: str) -> str:
    exp = _engine.pause_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{exp.name}' paused."


def ab_complete(experiment_id: str) -> str:
    exp = _engine.complete_experiment(experiment_id)
    if not exp:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{exp.name}' completed."


def ab_delete(experiment_id: str) -> str:
    ok = _engine.delete_experiment(experiment_id)
    if not ok:
        return f"[error] Experiment '{experiment_id}' not found."
    return f"Experiment '{experiment_id}' deleted."


def ab_assign(experiment_id: str, user_id: str = "") -> str:
    try:
        variant = _engine.assign_variant(experiment_id, user_id)
    except ValueError as e:
        return f"[error] {e}"
    if variant is None:
        return f"[error] Experiment '{experiment_id}' not found or not running."
    return variant


def ab_record(
    experiment_id: str, variant: str, metric_name: str = "conversion", value: float = 1.0, user_id: str = ""
) -> str:
    try:
        _engine.record_event(experiment_id, variant, metric_name, value, user_id)
    except KeyError:
        return f"[error] Experiment '{experiment_id}' not found."
    except (ValueError, RuntimeError) as e:
        return f"[error] {e}"
    unit = user_id or "none (will be excluded from the test: no unit of randomization)"
    return f"Event recorded: {experiment_id}/{variant}/{metric_name}={value} unit={unit}"


def ab_results(experiment_id: str) -> str:
    results = _engine.get_results(experiment_id)
    if not results:
        return f"[error] Experiment '{experiment_id}' not found."
    lines = [
        f"Results: {results['name']} ({results['status']})",
        f"Metric: {results['metric']} ({results['metric_type']}), test: {results['method']}, "
        f"control: {results['control']}",
        f"Events: {results['total_events']} analyzed / {results['events_stored']} stored"
        f" (dropped {results['events_dropped']}, no unit {results['events_unattributed']},"
        f" orphaned {results['events_orphaned']})",
    ]
    for row in results["variants"]:
        role = " [control]" if row["is_control"] else ""
        lines.append(
            f"  [{row['name']}]{role} units={row['sample_count']} events={row['events']} "
            f"unit_avg={row['unit_avg']} event_avg={row['avg_value']}"
        )
    if not results["comparisons"]:
        lines.append("  no comparison available (every arm is the control, or an arm has no units)")
    for c in results["comparisons"]:
        lift = "undefined (control mean is 0)" if c["lift"] is None else f"{c['lift']:+.2f}%"
        verdict = "significant" if c["significant"] else "not significant"
        lines.append(
            f"  {c['variant']} vs {c['control']}: diff={c['diff']:+.6g} "
            f"95% CI [{c['diff_ci_low']:.6g}, {c['diff_ci_high']:.6g}] lift={lift} "
            f"p={c['p_value']:.4g} p_adjusted={c['p_adjusted']:.4g} (alpha {results['alpha']}) -> {verdict}"
        )
    srm = results["srm"]
    if srm["imbalanced"]:
        lines.append(f"  WARNING sample ratio mismatch: chi2={srm['chi2']:.2f} p={srm['p_value']:.2e}")
    for warning in results["warnings"]:
        lines.append(f"  WARNING {warning}")
    lines.append(
        "Note: p_adjusted is Holm-Bonferroni across the comparisons; units, not events, are the "
        "sample size. Experiment state lives in this process only until it is persisted."
    )
    return "\n".join(lines)


def register_ab_testing_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="ab_create",
            description="Create an A/B test experiment with variants (JSON array)",
            parameters={
                "name": {"type": "string", "description": "Experiment name", "required": True},
                "description": {"type": "string", "description": "Experiment description", "required": True},
                "variants_json": {
                    "type": "string",
                    "description": (
                        'JSON array of variants [{"name":"A","weight":0.5,"config":{},"is_control":true},...]; '
                        "exactly one variant may be the control, and the first is used if none is marked"
                    ),
                    "required": True,
                },
                "metric_name": {
                    "type": "string",
                    "description": "Primary metric name (default conversion)",
                    "required": False,
                },
                "metric_type": {
                    "type": "string",
                    "description": (
                        "'rate' for a per-unit outcome (values 0..1, two-proportion z-test) or "
                        "'mean' for a per-unit continuous value (Welch t-test). Default rate."
                    ),
                    "required": False,
                },
            },
            handler=ab_create,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_list",
            description="List all A/B experiments",
            parameters={},
            handler=ab_list,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_get",
            description="Get experiment details",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            },
            handler=ab_get,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_start",
            description="Start an experiment",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            },
            handler=ab_start,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_pause",
            description="Pause an experiment",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            },
            handler=ab_pause,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_complete",
            description="Complete an experiment",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            },
            handler=ab_complete,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_delete",
            description="Delete an experiment",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            },
            handler=ab_delete,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_assign",
            description="Assign a user to a variant for an experiment",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
                "user_id": {
                    "type": "string",
                    "description": "Unit of randomization (required: without it the arm cannot be kept stable)",
                    "required": True,
                },
            },
            handler=ab_assign,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_record",
            description="Record an event/metric for an experiment variant",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
                "variant": {"type": "string", "description": "Variant name", "required": True},
                "metric_name": {"type": "string", "description": "Metric name (default conversion)", "required": False},
                "value": {"type": "number", "description": "Metric value (default 1.0)", "required": False},
                "user_id": {
                    "type": "string",
                    "description": (
                        "Unit of randomization. Events without it are counted but excluded from the "
                        "test, because they cannot be attributed to a subject"
                    ),
                    "required": False,
                },
            },
            handler=ab_record,
            category="ab_testing",
            timeout=10,
        )
    )
    registry.register(
        ToolSpec(
            name="ab_results",
            description="Get experiment results with statistical significance",
            parameters={
                "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
            },
            handler=ab_results,
            category="ab_testing",
            timeout=10,
        )
    )
