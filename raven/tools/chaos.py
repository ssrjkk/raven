from __future__ import annotations

import contextlib
from typing import Any

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

_chaos: Any = None


def _get_chaos() -> Any:
    global _chaos
    if _chaos is None:
        from raven.unique.chaos_engineering import ChaosEngineering
        _chaos = ChaosEngineering()
    return _chaos


async def chaos_inject(fault_type: str, target: str = "", duration_sec: float = 30.0, intensity: float = 0.5) -> str:
    ce = _get_chaos()
    from raven.unique.chaos_engineering import FaultConfig, FaultType
    try:
        ft = FaultType(fault_type)
    except ValueError:
        valid = [ft.value for ft in FaultType]
        return f"[error] Unknown fault type '{fault_type}'. Valid: {valid}"
    config = FaultConfig(fault_type=ft, target=target, duration_sec=duration_sec, intensity=intensity)
    try:
        result = await ce.injector.inject(config)
        return (
            f"Fault injected [id={result['id']}]:\n"
            f"- Type: {fault_type}\n"
            f"- Target: {target or 'system'}\n"
            f"- Duration: {duration_sec}s\n"
            f"- Intensity: {intensity}\n"
            f"Use chaos_recover {result['id']} to recover."
        )
    except Exception as e:
        logger.error("Chaos inject failed: {}", e)
        return f"[error] Injection failed: {e}"


async def chaos_recover(fault_id: str) -> str:
    ce = _get_chaos()
    result = await ce.injector.recover(fault_id)
    if result is None:
        return f"[error] Fault '{fault_id}' not found."
    if result["recovered"]:
        return f"Fault '{fault_id}' recovered."
    return f"[warn] Fault '{fault_id}' may not be fully recovered."


async def chaos_recover_all() -> str:
    ce = _get_chaos()
    results = await ce.injector.recover_all()
    return f"Recovered {len(results)} active faults."


def chaos_list_active() -> str:
    ce = _get_chaos()
    active = ce.injector.active_faults
    if not active:
        return "[info] No active faults."
    lines = [f"Active faults ({len(active)}):"]
    for fid, fault in active.items():
        lines.append(f"  [{fid}] {fault['config']['fault_type']} — target={fault['config']['target']}")
    return "\n".join(lines)


def chaos_list_history(fault_type: str = "") -> str:
    ce = _get_chaos()
    from raven.unique.chaos_engineering import FaultType
    ft = None
    if fault_type:
        with contextlib.suppress(ValueError):
            ft = FaultType(fault_type)
    history = ce.injector.get_history(ft)
    if not history:
        return "[info] No fault history."
    lines = [f"Fault history ({len(history)}):"]
    for h in history:
        lines.append(f"  [{h['id']}] {h['config']['fault_type']} — {'recovered' if h['recovered'] else 'active'} — {h['config']['target']}")
    return "\n".join(lines)


async def chaos_run_experiment(name: str, faults_json: str, hypothesis: str = "") -> str:
    ce = _get_chaos()
    from raven.unique.chaos_engineering import ExperimentConfig, ExperimentHypothesis, FaultConfig, FaultType
    try:
        import json
        faults_data = json.loads(faults_json)
    except json.JSONDecodeError as e:
        return f"[error] Invalid faults JSON: {e}"
    fault_configs = []
    for f in faults_data:
        try:
            ft = FaultType(f["fault_type"])
        except (ValueError, KeyError):
            return f"[error] Invalid fault_type in config: {f.get('fault_type', 'missing')}"
        fault_configs.append(FaultConfig(
            fault_type=ft,
            target=f.get("target", ""),
            duration_sec=f.get("duration_sec", 30.0),
            intensity=f.get("intensity", 0.5),
        ))
    hyp = ExperimentHypothesis(description=hypothesis or "No hypothesis specified")
    config = ExperimentConfig(name=name, hypothesis=hyp, faults=fault_configs)
    try:
        result = await ce.run_experiment(config)
        return (
            f"Experiment '{name}' completed:\n"
            f"- Status: {result.status.value}\n"
            f"- Resilience score: {result.resilience_score:.4f}\n"
            f"- Hypothesis validated: {result.hypothesis_validated}\n"
            f"- Faults injected: {len(result.faults_injected)}\n"
            f"- Faults recovered: {len(result.faults_recovered)}\n"
            f"- Experiment ID: {result.experiment_id}"
        )
    except Exception as e:
        logger.error("Chaos experiment failed: {}", e)
        return f"[error] Experiment failed: {e}"


def chaos_experiment_report(experiment_id: str) -> str:
    ce = _get_chaos()
    try:
        report = ce.generate_report(experiment_id)
    except ValueError as e:
        return f"[error] {e}"
    return (
        f"Experiment Report: {report['name']}\n"
        f"- Status: {report['status']}\n"
        f"- Duration: {report['duration_sec']}s\n"
        f"- Resilience: {report['resilience_score']}\n"
        f"- Steadiness: {report['steadiness_score']}\n"
        f"- Recovery rate: {report['recovery_rate']}\n"
        f"- Hypothesis validated: {report['hypothesis']['validated']}\n"
        f"- Faults: {report['faults_injected']} injected, {report['faults_recovered']} recovered\n"
        f"- Errors: {len(report['errors'])}"
    )


def chaos_resilience_summary() -> str:
    ce = _get_chaos()
    summary = ce.get_resilience_summary()
    return (
        f"Resilience Summary\n"
        f"- Experiments run: {summary['experiments_run']}\n"
        f"- Average resilience: {summary['avg_resilience']:.4f}\n"
        f"- Average steadiness: {summary['avg_steadiness']:.4f}\n"
        f"- Hypotheses validated: {summary['hypotheses_validated']}\n"
        f"- Total faults injected: {summary['total_faults_injected']}\n"
        f"- Total faults recovered: {summary['total_faults_recovered']}"
    )


def register_chaos_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="chaos_inject",
        description="Inject a fault into the system (service_kill, network_latency, disk_fill, cpu_storm, memory_leak, process_kill)",
        parameters={
            "fault_type": {"type": "string", "description": "Fault type", "required": True},
            "target": {"type": "string", "description": "Target service/process name", "required": False},
            "duration_sec": {"type": "number", "description": "Duration in seconds (default 30)", "required": False},
            "intensity": {"type": "number", "description": "Intensity 0-1 (default 0.5)", "required": False},
        },
        handler=chaos_inject,
        category="chaos",
        timeout=60,
    ))
    registry.register(ToolSpec(
        name="chaos_recover",
        description="Recover a specific fault by ID",
        parameters={
            "fault_id": {"type": "string", "description": "Fault ID to recover", "required": True},
        },
        handler=chaos_recover,
        category="chaos",
        timeout=15,
    ))
    registry.register(ToolSpec(
        name="chaos_recover_all",
        description="Recover all active faults",
        parameters={},
        handler=chaos_recover_all,
        category="chaos",
        timeout=15,
    ))
    registry.register(ToolSpec(
        name="chaos_list_active",
        description="List all active (unrecovered) faults",
        parameters={},
        handler=chaos_list_active,
        category="chaos",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="chaos_list_history",
        description="List fault injection history",
        parameters={
            "fault_type": {"type": "string", "description": "Optional fault type filter", "required": False},
        },
        handler=chaos_list_history,
        category="chaos",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="chaos_run_experiment",
        description="Run a full chaos experiment with multiple faults, monitoring, and resilience scoring",
        parameters={
            "name": {"type": "string", "description": "Experiment name", "required": True},
            "faults_json": {"type": "string", "description": "JSON array of fault configs", "required": True},
            "hypothesis": {"type": "string", "description": "Hypothesis description", "required": False},
        },
        handler=chaos_run_experiment,
        category="chaos",
        timeout=600,
    ))
    registry.register(ToolSpec(
        name="chaos_experiment_report",
        description="Generate a report for a completed experiment",
        parameters={
            "experiment_id": {"type": "string", "description": "Experiment ID", "required": True},
        },
        handler=chaos_experiment_report,
        category="chaos",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="chaos_resilience_summary",
        description="Get resilience summary across all experiments",
        parameters={},
        handler=chaos_resilience_summary,
        category="chaos",
        timeout=10,
    ))
