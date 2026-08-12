from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import raven.tools.chaos as chaos
from raven.core.task_engine.tool_registry import ToolRegistry
from raven.unique.chaos_engineering import (
    ExperimentConfig,
    ExperimentStatus,
    FaultConfig,
    FaultType,
)

ALL_FAULT_TYPES = [
    "service_kill",
    "network_latency",
    "disk_fill",
    "cpu_storm",
    "memory_leak",
    "process_kill",
]


class _FakeInjector:
    def __init__(self) -> None:
        self.active_faults: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.inject_result: dict[str, Any] = {"id": "fault-1"}
        self.inject_error: Exception | None = None
        self.recover_result: dict[str, Any] | None = {"id": "fault-1", "recovered": True}
        self.recover_all_result: list[dict[str, Any]] = [{"id": "fault-1"}]
        self.injected_configs: list[FaultConfig] = []
        self.last_history_fault_type: FaultType | None = None

    async def inject(self, config: FaultConfig) -> dict[str, Any]:
        self.injected_configs.append(config)
        if self.inject_error is not None:
            raise self.inject_error
        return self.inject_result

    async def recover(self, fault_id: str) -> dict[str, Any] | None:
        return self.recover_result

    async def recover_all(self) -> list[dict[str, Any]]:
        return self.recover_all_result

    def get_history(self, fault_type: FaultType | None = None) -> list[dict[str, Any]]:
        self.last_history_fault_type = fault_type
        return self.history


class _FakeChaosEngineering:
    def __init__(self) -> None:
        self.injector = _FakeInjector()
        self.experiment_result: Any = None
        self.experiment_error: Exception | None = None
        self.last_experiment_config: ExperimentConfig | None = None
        self.report: dict[str, Any] | None = None
        self.report_error: Exception | None = None
        self.summary: dict[str, Any] = {
            "experiments_run": 3,
            "avg_resilience": 0.75,
            "avg_steadiness": 0.8,
            "hypotheses_validated": 2,
            "total_faults_injected": 9,
            "total_faults_recovered": 8,
        }

    async def run_experiment(self, config: ExperimentConfig) -> Any:
        self.last_experiment_config = config
        if self.experiment_error is not None:
            raise self.experiment_error
        return self.experiment_result

    def generate_report(self, experiment_id: str) -> dict[str, Any]:
        if self.report_error is not None:
            raise self.report_error
        if self.report is None:
            raise ValueError(f"Experiment not found: {experiment_id}")
        return self.report

    def get_resilience_summary(self) -> dict[str, Any]:
        return self.summary


@pytest.fixture
def ce(monkeypatch: pytest.MonkeyPatch) -> _FakeChaosEngineering:
    fake = _FakeChaosEngineering()
    monkeypatch.setattr(chaos, "_chaos", fake)
    return fake


class TestGetChaos:
    def test_returns_cached_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeChaosEngineering()
        monkeypatch.setattr(chaos, "_chaos", fake)
        assert chaos._get_chaos() is fake

    def test_initializes_on_demand(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeChaosEngineering()
        monkeypatch.setattr(chaos, "_chaos", None)
        monkeypatch.setattr("raven.unique.chaos_engineering.ChaosEngineering", lambda: fake)
        assert chaos._get_chaos() is fake
        assert chaos._get_chaos() is fake


class TestChaosInject:
    @pytest.mark.parametrize("fault_type", ALL_FAULT_TYPES)
    async def test_success_each_fault_type(
        self, ce: _FakeChaosEngineering, fault_type: str
    ) -> None:
        result = await chaos.chaos_inject(fault_type, target="nginx", duration_sec=30.0, intensity=0.5)
        assert "Fault injected [id=fault-1]" in result
        assert f"- Type: {fault_type}" in result
        assert "- Target: nginx" in result
        assert "- Duration: 30.0s" in result
        assert "- Intensity: 0.5" in result
        assert "Use chaos_recover fault-1 to recover." in result
        assert ce.injector.injected_configs[-1].fault_type == FaultType(fault_type)

    async def test_default_target_is_system(self, ce: _FakeChaosEngineering) -> None:
        result = await chaos.chaos_inject("cpu_storm")
        assert "- Target: system" in result

    async def test_unknown_fault_type(self, ce: _FakeChaosEngineering) -> None:
        result = await chaos.chaos_inject("bogus")
        assert "[error] Unknown fault type 'bogus'" in result
        assert "Valid: " in result

    async def test_injection_error(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.inject_error = RuntimeError("boom")
        result = await chaos.chaos_inject("service_kill")
        assert "[error] Injection failed: boom" in result


class TestChaosRecover:
    async def test_success(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.recover_result = {"id": "f1", "recovered": True}
        result = await chaos.chaos_recover("f1")
        assert result == "Fault 'f1' recovered."

    async def test_not_found(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.recover_result = None
        result = await chaos.chaos_recover("nope")
        assert result == "[error] Fault 'nope' not found."

    async def test_partially_recovered(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.recover_result = {"id": "f1", "recovered": False}
        result = await chaos.chaos_recover("f1")
        assert result == "[warn] Fault 'f1' may not be fully recovered."

    async def test_recover_all(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.recover_all_result = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = await chaos.chaos_recover_all()
        assert result == "Recovered 3 active faults."


class TestChaosListActive:
    def test_empty(self, ce: _FakeChaosEngineering) -> None:
        assert chaos.chaos_list_active() == "[info] No active faults."

    def test_nonempty(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.active_faults = {
            "f1": {"config": {"fault_type": "cpu_storm", "target": "worker"}},
            "f2": {"config": {"fault_type": "disk_fill", "target": "/tmp"}},
        }
        result = chaos.chaos_list_active()
        assert "Active faults (2):" in result
        assert "[f1] cpu_storm — target=worker" in result
        assert "[f2] disk_fill — target=/tmp" in result


class TestChaosListHistory:
    def test_empty(self, ce: _FakeChaosEngineering) -> None:
        assert chaos.chaos_list_history() == "[info] No fault history."

    def test_nonempty(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.history = [
            {"id": "f1", "config": {"fault_type": "disk_fill", "target": "/tmp"}, "recovered": True},
            {"id": "f2", "config": {"fault_type": "memory_leak", "target": "svc"}, "recovered": False},
        ]
        result = chaos.chaos_list_history()
        assert "Fault history (2):" in result
        assert "[f1] disk_fill — recovered — /tmp" in result
        assert "[f2] memory_leak — active — svc" in result

    def test_valid_fault_type_filter(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.history = [{"id": "f1", "config": {"fault_type": "cpu_storm", "target": "w"}, "recovered": True}]
        result = chaos.chaos_list_history("cpu_storm")
        assert "Fault history (1):" in result
        assert ce.injector.last_history_fault_type == FaultType.CPU_STORM

    def test_invalid_fault_type_filter(self, ce: _FakeChaosEngineering) -> None:
        ce.injector.history = [{"id": "f1", "config": {"fault_type": "cpu_storm", "target": "w"}, "recovered": True}]
        result = chaos.chaos_list_history("bogus")
        assert "Fault history (1):" in result
        assert ce.injector.last_history_fault_type is None


class TestChaosRunExperiment:
    async def test_success(self, ce: _FakeChaosEngineering) -> None:
        ce.experiment_result = SimpleNamespace(
            status=ExperimentStatus.COMPLETED,
            resilience_score=0.8571,
            hypothesis_validated=True,
            faults_injected=[{"id": "x"}],
            faults_recovered=[{"id": "x"}],
            experiment_id="exp-1",
        )
        result = await chaos.chaos_run_experiment(
            "bench",
            '[{"fault_type": "network_latency", "target": "eth0", "duration_sec": 5, "intensity": 0.2}]',
            hypothesis="service stays up",
        )
        assert "Experiment 'bench' completed:" in result
        assert "- Status: completed" in result
        assert "- Resilience score: 0.8571" in result
        assert "- Hypothesis validated: True" in result
        assert "- Faults injected: 1" in result
        assert "- Faults recovered: 1" in result
        assert "- Experiment ID: exp-1" in result
        assert ce.last_experiment_config is not None
        assert ce.last_experiment_config.name == "bench"
        assert ce.last_experiment_config.hypothesis.description == "service stays up"
        assert len(ce.last_experiment_config.faults) == 1

    async def test_empty_faults(self, ce: _FakeChaosEngineering) -> None:
        ce.experiment_result = SimpleNamespace(
            status=ExperimentStatus.COMPLETED,
            resilience_score=1.0,
            hypothesis_validated=True,
            faults_injected=[],
            faults_recovered=[],
            experiment_id="exp-0",
        )
        result = await chaos.chaos_run_experiment("empty", "[]")
        assert "- Faults injected: 0" in result
        assert ce.last_experiment_config is not None
        assert ce.last_experiment_config.hypothesis.description == "No hypothesis specified"

    async def test_invalid_json(self, ce: _FakeChaosEngineering) -> None:
        result = await chaos.chaos_run_experiment("bench", "not json")
        assert result.startswith("[error] Invalid faults JSON:")

    async def test_invalid_fault_type(self, ce: _FakeChaosEngineering) -> None:
        result = await chaos.chaos_run_experiment("bench", '[{"fault_type": "bogus"}]')
        assert result == "[error] Invalid fault_type in config: bogus"

    async def test_missing_fault_type(self, ce: _FakeChaosEngineering) -> None:
        result = await chaos.chaos_run_experiment("bench", "[{}]")
        assert result == "[error] Invalid fault_type in config: missing"

    async def test_experiment_error(self, ce: _FakeChaosEngineering) -> None:
        ce.experiment_error = RuntimeError("kaboom")
        result = await chaos.chaos_run_experiment("bench", '[{"fault_type": "cpu_storm"}]')
        assert result == "[error] Experiment failed: kaboom"


class TestChaosExperimentReport:
    def test_success(self, ce: _FakeChaosEngineering) -> None:
        ce.report = {
            "name": "bench",
            "status": "completed",
            "duration_sec": 12.5,
            "resilience_score": 0.8,
            "steadiness_score": 0.9,
            "recovery_rate": 1.0,
            "hypothesis": {"validated": True},
            "faults_injected": 2,
            "faults_recovered": 2,
            "errors": [],
        }
        result = chaos.chaos_experiment_report("exp-1")
        assert "Experiment Report: bench" in result
        assert "- Status: completed" in result
        assert "- Duration: 12.5s" in result
        assert "- Resilience: 0.8" in result
        assert "- Steadiness: 0.9" in result
        assert "- Recovery rate: 1.0" in result
        assert "- Hypothesis validated: True" in result
        assert "- Faults: 2 injected, 2 recovered" in result
        assert "- Errors: 0" in result

    def test_not_found(self, ce: _FakeChaosEngineering) -> None:
        ce.report_error = ValueError("Experiment not found: exp-x")
        result = chaos.chaos_experiment_report("exp-x")
        assert result == "[error] Experiment not found: exp-x"


class TestChaosResilienceSummary:
    def test_success(self, ce: _FakeChaosEngineering) -> None:
        result = chaos.chaos_resilience_summary()
        assert "Resilience Summary" in result
        assert "- Experiments run: 3" in result
        assert "- Average resilience: 0.7500" in result
        assert "- Average steadiness: 0.8000" in result
        assert "- Hypotheses validated: 2" in result
        assert "- Total faults injected: 9" in result
        assert "- Total faults recovered: 8" in result


class TestRegisterChaosTools:
    def test_registers_all_tools(self) -> None:
        registry = ToolRegistry()
        chaos.register_chaos_tools(registry)
        names = [
            "chaos_inject",
            "chaos_recover",
            "chaos_recover_all",
            "chaos_list_active",
            "chaos_list_history",
            "chaos_run_experiment",
            "chaos_experiment_report",
            "chaos_resilience_summary",
        ]
        for name in names:
            spec = registry.get(name)
            assert spec is not None
            assert spec.category == "chaos"
