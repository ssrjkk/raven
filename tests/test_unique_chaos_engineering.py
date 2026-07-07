from __future__ import annotations

import asyncio

import pytest

from raven.unique.chaos_engineering import (
    ChaosEngineering,
    ExperimentConfig,
    ExperimentHypothesis,
    ExperimentResult,
    ExperimentStatus,
    FaultConfig,
    FaultInjector,
    FaultType,
    SystemMonitor,
)


class TestEnums:
    def test_fault_type_values(self):
        assert FaultType.SERVICE_KILL.value == "service_kill"
        assert FaultType.NETWORK_LATENCY.value == "network_latency"
        assert FaultType.DISK_FILL.value == "disk_fill"
        assert FaultType.CPU_STORM.value == "cpu_storm"
        assert FaultType.MEMORY_LEAK.value == "memory_leak"
        assert FaultType.PROCESS_KILL.value == "process_kill"

    def test_experiment_status_values(self):
        assert ExperimentStatus.PENDING.value == "pending"
        assert ExperimentStatus.RUNNING.value == "running"
        assert ExperimentStatus.RECOVERING.value == "recovering"
        assert ExperimentStatus.COMPLETED.value == "completed"
        assert ExperimentStatus.FAILED.value == "failed"
        assert ExperimentStatus.ABORTED.value == "aborted"


class TestDataclasses:
    def test_fault_config_defaults(self):
        config = FaultConfig(fault_type=FaultType.SERVICE_KILL)
        assert config.target == ""
        assert config.duration_sec == 30.0
        assert config.intensity == 0.5
        assert config.metadata == {}

    def test_experiment_config_creation(self):
        hypothesis = ExperimentHypothesis(
            description="System should recover",
            success_criteria=["cpu below 80"],
        )
        config = ExperimentConfig(
            name="test-experiment",
            hypothesis=hypothesis,
            faults=[FaultConfig(fault_type=FaultType.NETWORK_LATENCY)],
            tags=["networking"],
        )
        assert config.name == "test-experiment"
        assert len(config.faults) == 1
        assert config.tags == ["networking"]

    def test_experiment_hypothesis_defaults(self):
        h = ExperimentHypothesis(description="test")
        assert h.expected_behavior == ""
        assert h.success_criteria == []
        assert h.metrics_expected == {}

    def test_experiment_result_defaults(self):
        config = ExperimentConfig(
            name="x", hypothesis=ExperimentHypothesis(description="d")
        )
        result = ExperimentResult(
            experiment_id="e1",
            config=config,
            status=ExperimentStatus.PENDING,
        )
        assert result.start_time == 0.0
        assert result.faults_injected == []
        assert result.errors == []


class TestFaultInjector:
    def setup_method(self) -> None:
        self.injector = FaultInjector()

    @pytest.mark.asyncio
    async def test_inject_service_kill_simulated(self):
        config = FaultConfig(
            fault_type=FaultType.SERVICE_KILL, target="nginx", duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert "id" in result
        assert result["config"]["fault_type"] == "service_kill"
        assert result["config"]["target"] == "nginx"
        assert result["recovered"] is False
        assert result["error"] == ""

    @pytest.mark.asyncio
    async def test_inject_network_latency_simulated(self):
        config = FaultConfig(
            fault_type=FaultType.NETWORK_LATENCY,
            target="eth0",
            intensity=0.3,
            duration_sec=0.01,
        )
        result = await self.injector.inject(config)
        assert result["details"]["latency_ms"] == 1500.0
        assert result["details"]["simulated"] is True

    @pytest.mark.asyncio
    async def test_inject_disk_fill_simulated(self):
        config = FaultConfig(
            fault_type=FaultType.DISK_FILL, intensity=0.5, duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert result["details"]["fill_percent"] == 75.0
        assert result["details"]["simulated"] is True

    @pytest.mark.asyncio
    async def test_inject_cpu_storm_simulated(self):
        config = FaultConfig(
            fault_type=FaultType.CPU_STORM, intensity=0.5, duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert result["details"]["simulated"] is True

    @pytest.mark.asyncio
    async def test_inject_memory_leak_simulated(self):
        config = FaultConfig(
            fault_type=FaultType.MEMORY_LEAK, intensity=0.5, duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert result["details"]["simulated"] is True

    @pytest.mark.asyncio
    async def test_recover_fault(self):
        config = FaultConfig(
            fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01
        )
        injected = await self.injector.inject(config)
        recovered = await self.injector.recover(injected["id"])
        assert recovered is not None
        assert recovered["recovered"] is True

    @pytest.mark.asyncio
    async def test_recover_nonexistent(self):
        result = await self.injector.recover("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_recover_all(self):
        cfg1 = FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01)
        cfg2 = FaultConfig(fault_type=FaultType.SERVICE_KILL, target="redis", duration_sec=0.01)
        await self.injector.inject(cfg1)
        await self.injector.inject(cfg2)
        results = await self.injector.recover_all()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_history(self):
        config = FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01)
        await self.injector.inject(config)
        history = self.injector.get_history()
        assert len(history) == 1
        history_filtered = self.injector.get_history(FaultType.SERVICE_KILL)
        assert len(history_filtered) == 0

    def test_active_faults_property(self):
        assert self.injector.active_faults == {}

    def test_clear_history(self):
        assert self.injector.clear_history() is None


class TestSystemMonitor:
    def setup_method(self) -> None:
        self.monitor = SystemMonitor(collect_interval_sec=0.05)

    @pytest.mark.asyncio
    async def test_collect_snapshot_without_psutil(self):
        snapshot = await self.monitor._collect_snapshot()
        assert 0 <= snapshot.cpu_percent <= 100
        assert 0 <= snapshot.memory_percent <= 100
        assert 0 <= snapshot.disk_percent <= 100
        assert 100 <= snapshot.processes_running <= 500
        assert snapshot.network_latency_ms == 0.0
        assert snapshot.timestamp > 0

    def test_get_average_metrics_empty(self):
        metrics = self.monitor.get_average_metrics([])
        assert metrics == {"cpu": 0.0, "memory": 0.0, "disk": 0.0, "processes": 0.0, "latency": 0.0}


class TestChaosEngineering:
    def setup_method(self) -> None:
        self.ce = ChaosEngineering()

    def test_properties(self):
        assert self.ce.injector is not None
        assert self.ce.monitor is not None

    def test_get_experiment_nonexistent(self):
        assert self.ce.get_experiment("nonexistent") is None

    def test_list_experiments_empty(self):
        assert self.ce.list_experiments() == []

    def test_list_experiments_by_status_empty(self):
        assert self.ce.list_experiments(ExperimentStatus.COMPLETED) == []

    def test_generate_report_unknown(self):
        with pytest.raises(ValueError, match="Experiment not found"):
            self.ce.generate_report("nonexistent")

    def test_generate_report_contains_key_sections(self):
        hypothesis = ExperimentHypothesis(
            description="System should handle latency",
            success_criteria=["cpu below 80", "all faults recover"],
        )
        config = ExperimentConfig(
            name="latency-test",
            hypothesis=hypothesis,
            faults=[FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01)],
        )
        result = ExperimentResult(
            experiment_id="exp-1",
            config=config,
            status=ExperimentStatus.COMPLETED,
            start_time=100.0,
            end_time=200.0,
            metrics_before={"cpu": 30.0, "memory": 40.0, "disk": 50.0, "processes": 200.0, "latency": 0.0},
            metrics_after={"cpu": 50.0, "memory": 45.0, "disk": 55.0, "processes": 190.0, "latency": 0.0},
            faults_injected=[{"id": "f1", "type": "network_latency"}],
            faults_recovered=[{"id": "f1", "type": "network_latency"}],
            hypothesis_validated=True,
            resilience_score=0.85,
        )
        self.ce._experiments["exp-1"] = result
        report = self.ce.generate_report("exp-1")
        assert report["experiment_id"] == "exp-1"
        assert report["name"] == "latency-test"
        assert "hypothesis" in report
        assert report["hypothesis"]["validated"] is True
        assert "resilience_score" in report
        assert "steadiness_score" in report
        assert "metrics" in report
        assert "before" in report["metrics"]
        assert "after" in report["metrics"]
        assert "delta" in report["metrics"]
        assert report["faults_injected"] == 1
        assert report["faults_recovered"] == 1
        assert report["recovery_rate"] == 1.0

    def test_resilience_summary_empty(self):
        summary = self.ce.get_resilience_summary()
        assert summary["experiments_run"] == 0
        assert summary["avg_resilience"] == 0.0

    @pytest.mark.asyncio
    async def test_abort_experiment_nonexistent(self):
        assert await self.ce.abort_experiment("nope") is False

    @pytest.mark.asyncio
    async def test_run_experiment_empty_faults(self):
        hypothesis = ExperimentHypothesis(description="Baseline test")
        config = ExperimentConfig(
            name="empty-test",
            hypothesis=hypothesis,
            faults=[],
            recovery_timeout_sec=0.1,
        )
        result = await self.ce.run_experiment(config)
        assert result.status == ExperimentStatus.COMPLETED
        assert result.config.name == "empty-test"
        assert result.faults_injected == []
        assert result.faults_recovered == []
        assert result.end_time > result.start_time

    def test_validate_hypothesis_no_criteria(self):
        hypothesis = ExperimentHypothesis(description="test")
        config = ExperimentConfig(name="t", hypothesis=hypothesis)
        result = ExperimentResult(
            experiment_id="e1",
            config=config,
            status=ExperimentStatus.COMPLETED,
        )
        assert self.ce._validate_hypothesis(result) is True
