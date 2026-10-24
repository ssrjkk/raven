from __future__ import annotations

import asyncio
import contextlib
import shutil
import subprocess
import sys
import time
import types
from collections import namedtuple
from itertools import chain, repeat
from pathlib import Path
from typing import Any

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
    SystemSnapshot,
)

_DiskUsage = namedtuple("_DiskUsage", "total used free")


def _small_free_space(monkeypatch: pytest.MonkeyPatch) -> None:
    # The injector caps a fill at 100 MB, so without this every disk-fill test would write that.
    monkeypatch.setattr(shutil, "disk_usage", lambda path: _DiskUsage(3_000_000, 2_000_000, 1_000_000))


def _fake_proc_factory() -> tuple[Any, list[int]]:
    killed: list[int] = []

    class _FakeProc:
        def __init__(self, pid: int, name: str) -> None:
            self.info: dict[str, Any] = {"pid": pid, "name": name}

        def kill(self) -> None:
            killed.append(self.info["pid"])

    return _FakeProc, killed


def _install_fake_psutil(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cpu: float = 12.5,
    mem: float = 40.0,
    disk: float = 60.0,
    pids: list[int] | None = None,
    procs: list[tuple[int, str]] | None = None,
) -> list[int]:
    _FakeProc, killed = _fake_proc_factory()
    mod: Any = types.ModuleType("psutil")
    mod.cpu_percent = lambda interval: cpu

    class _VM:
        percent = mem

    class _DU:
        percent = disk

    mod.virtual_memory = lambda: _VM()
    mod.disk_usage = lambda path: _DU()
    mod.pids = lambda: pids or [1, 2, 3]
    mod.process_iter = lambda attrs=None: [
        _FakeProc(pid, name) for pid, name in (procs or [])
    ]
    monkeypatch.setitem(sys.modules, "psutil", mod)
    return killed


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
    async def test_inject_network_latency(self):
        config = FaultConfig(
            fault_type=FaultType.NETWORK_LATENCY,
            target="eth0",
            intensity=0.3,
            duration_sec=0.01,
        )
        result = await self.injector.inject(config)
        assert result["details"]["latency_ms"] == 1500.0

    @pytest.mark.asyncio
    async def test_inject_disk_fill(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _small_free_space(monkeypatch)
        config = FaultConfig(
            fault_type=FaultType.DISK_FILL, target=str(tmp_path), intensity=0.5, duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert result["details"]["fill_percent"] == 75.0
        fill = Path(result["details"]["file"])
        assert fill.parent == tmp_path
        assert fill.exists()
        assert fill.stat().st_size == result["details"]["bytes_written"]

    @pytest.mark.asyncio
    async def test_recover_removes_the_file_injection_recorded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _small_free_space(monkeypatch)
        result = await self.injector.inject(
            FaultConfig(fault_type=FaultType.DISK_FILL, target=str(tmp_path), duration_sec=0.01)
        )
        fill = Path(result["details"]["file"])
        # Recovery must not re-derive the path from a target that may no longer be the one used.
        result["config"]["target"] = str(tmp_path / "moved-away")
        await self.injector.recover(result["id"])
        assert not fill.exists()
        assert result["recovered"] is True

    @pytest.mark.asyncio
    async def test_inject_cpu_storm(self):
        config = FaultConfig(
            fault_type=FaultType.CPU_STORM, intensity=0.5, duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert "cores" in result["details"]
        assert result["error"] == ""

    @pytest.mark.asyncio
    async def test_inject_memory_leak(self):
        config = FaultConfig(
            fault_type=FaultType.MEMORY_LEAK, intensity=0.5, duration_sec=0.01
        )
        result = await self.injector.inject(config)
        assert result["details"]["mb"] == 512
        assert result["error"] == ""

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
        # should not raise
        self.injector.clear_history()


class TestSystemMonitor:
    def setup_method(self) -> None:
        self.monitor = SystemMonitor(collect_interval_sec=0.05)

    @pytest.mark.asyncio
    async def test_collect_snapshot_without_psutil(self, monkeypatch: pytest.MonkeyPatch):
        async def _no_latency() -> float:
            return 0.0

        monkeypatch.setattr(self.monitor, "_get_network_latency", _no_latency)
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


async def _wait_for_snapshots(m: SystemMonitor, limit: int = 200) -> None:
    # The collector samples through a worker thread, so a fixed sleep loses the race on a busy runner.
    for _ in range(limit):
        if m.get_snapshots():
            return
        await asyncio.sleep(0.01)


class TestSystemMonitorStartStop:
    async def test_start_collects_then_stop(self, monkeypatch: pytest.MonkeyPatch):
        m = SystemMonitor(collect_interval_sec=0.01)

        async def _fast_latency() -> float:
            return 3.0

        monkeypatch.setattr(m, "_get_network_latency", _fast_latency)
        await m.start()
        await m.start()  # second start hits the already-running early return
        await _wait_for_snapshots(m)
        snaps = await m.stop()
        assert len(snaps) >= 1
        assert m._task is None

    async def test_start_collects_through_a_slow_first_sample(self, monkeypatch: pytest.MonkeyPatch):
        m = SystemMonitor(collect_interval_sec=0.01)

        async def _slow_snapshot() -> SystemSnapshot:
            await asyncio.sleep(0.2)
            return SystemSnapshot(timestamp=1.0)

        monkeypatch.setattr(m, "_collect_snapshot", _slow_snapshot)
        await m.start()
        await _wait_for_snapshots(m)
        snaps = await m.stop()
        assert len(snaps) >= 1

    def test_get_snapshots_filters_by_since(self):
        m = SystemMonitor()
        m._snapshots = [SystemSnapshot(timestamp=10.0), SystemSnapshot(timestamp=20.0)]
        assert len(m.get_snapshots()) == 2
        assert len(m.get_snapshots(15.0)) == 1

    def test_psutil_sample_paths(self, monkeypatch: pytest.MonkeyPatch):
        _install_fake_psutil(monkeypatch, cpu=33.0, mem=44.0, disk=55.0, pids=[1, 2, 3, 4])
        m = SystemMonitor()
        assert m._get_cpu() == 33.0
        assert m._get_memory() == 44.0
        assert m._get_disk() == 55.0
        assert m._get_process_count() == 4

    async def test_network_latency_parses_ping_output(self, monkeypatch: pytest.MonkeyPatch):
        class _Proc:
            async def communicate(self) -> tuple[bytes, bytes]:
                return (b"PING: bytes=32 time=17.3 ms TTL=55\n", b"")

        async def _fake_exec(*args: object, **kwargs: object) -> _Proc:
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
        m = SystemMonitor()
        assert await m._get_network_latency() == 17.3

    async def test_network_latency_subprocess_error(self, monkeypatch: pytest.MonkeyPatch):
        async def _boom(*args: object, **kwargs: object) -> None:
            raise FileNotFoundError("no ping")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
        m = SystemMonitor()
        assert await m._get_network_latency() == 0.0


class TestFaultInjectorBranches:
    async def test_service_kill_no_target(self):
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.SERVICE_KILL, duration_sec=0.01))
        assert res["error"] == "No service target specified"

    async def test_service_kill_psutil_found(self, monkeypatch: pytest.MonkeyPatch):
        killed = _install_fake_psutil(monkeypatch, procs=[(101, "nginx"), (202, "other")])
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.SERVICE_KILL, target="nginx", duration_sec=0.01))
        assert res["details"]["killed_pid"] == 101
        assert killed == [101]

    async def test_service_kill_psutil_not_found(self, monkeypatch: pytest.MonkeyPatch):
        _install_fake_psutil(monkeypatch, procs=[(1, "system")])
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.SERVICE_KILL, target="ghostd", duration_sec=0.01))
        assert res["details"]["simulated"] is True

    async def test_process_kill_no_target(self):
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.PROCESS_KILL, duration_sec=0.01))
        assert res["error"] == "No process target specified"

    async def test_process_kill_psutil_found(self, monkeypatch: pytest.MonkeyPatch):
        _install_fake_psutil(monkeypatch, procs=[(303, "firefox.exe")])
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.PROCESS_KILL, target="firefox", duration_sec=0.01))
        assert res["details"]["killed_pid"] == 303

    async def test_process_kill_psutil_not_found(self, monkeypatch: pytest.MonkeyPatch):
        _install_fake_psutil(monkeypatch, procs=[(1, "notepad")])
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.PROCESS_KILL, target="zzz", duration_sec=0.01))
        assert res["details"]["simulated"] is True

    async def test_process_kill_without_psutil(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delitem(sys.modules, "psutil", raising=False)
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.PROCESS_KILL, target="anything", duration_sec=0.01))
        assert res["details"]["simulated"] is True

    async def test_disk_fill_no_free_space(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delitem(sys.modules, "psutil", raising=False)
        inj = FaultInjector()
        res = await inj.inject(
            FaultConfig(fault_type=FaultType.DISK_FILL, target=str(tmp_path), intensity=1.0, duration_sec=0.01)
        )
        assert res["details"]["error"] == "no free space"

    async def test_disk_fill_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        def _boom(path: object) -> None:
            raise OSError("disk err")

        monkeypatch.setattr(shutil, "disk_usage", _boom)
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.DISK_FILL, target=str(tmp_path), duration_sec=0.01))
        assert "disk err" in res["details"]["error"]

    async def test_inject_dispatch_error_recorded(self, monkeypatch: pytest.MonkeyPatch):
        inj = FaultInjector()

        def _raise(fault: dict[str, Any]) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(inj, "_inject_service_kill", _raise)
        res = await inj.inject(FaultConfig(fault_type=FaultType.SERVICE_KILL, target="nginx", duration_sec=0.01))
        assert "boom" in res["error"]

    async def test_cpu_burn_completes(self):
        inj = FaultInjector()
        await inj._cpu_burn(1, 0.01, "f1")

    async def test_recover_already_recovered(self):
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01))
        await inj.recover(res["id"])
        again = await inj.recover(res["id"])
        assert again is not None
        assert again["recovered"] is True

    async def test_recover_failure(self, monkeypatch: pytest.MonkeyPatch):
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01))

        def _boom(fault: dict[str, Any]) -> None:
            msg = "rec boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(inj, "_recover_fault", _boom)
        r = await inj.recover(res["id"])
        assert r is not None
        assert "Recovery failed" in r["error"]

    def test_recover_fault_cpu_and_memory(self):
        inj = FaultInjector()
        inj._recover_fault({"config": {"fault_type": "cpu_storm"}, "id": "c"})
        inj._recover_fault({"config": {"fault_type": "memory_leak"}, "id": "m"})

    def test_recover_fault_process_and_service(self):
        inj = FaultInjector()
        inj._recover_fault({"config": {"fault_type": "process_kill", "target": "p"}, "id": "x"})
        inj._recover_fault({"config": {"fault_type": "service_kill", "target": "s"}, "id": "y"})

    def test_recover_fault_disk_fill_removes(self, tmp_path: Path):
        inj = FaultInjector()
        fill = tmp_path / ".chaos_disk_fill_d1.tmp"
        fill.write_bytes(b"x")
        inj._recover_fault({"config": {"fault_type": "disk_fill", "target": str(tmp_path)}, "id": "d1"})
        assert not fill.exists()


class TestFaultInjectorTcBranch:
    def _fake_linux_tc(self, monkeypatch: pytest.MonkeyPatch, run: Any) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        monkeypatch.setattr(shutil, "which", lambda name: "/sbin/tc" if name == "tc" else None)
        monkeypatch.setattr(subprocess, "run", run)

    async def test_tc_latency_real_applied(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[Any] = []
        self._fake_linux_tc(monkeypatch, lambda *a, **k: calls.append(a))
        inj = FaultInjector()
        res = await inj.inject(
            FaultConfig(fault_type=FaultType.NETWORK_LATENCY, target="eth0", intensity=0.2, duration_sec=0.01)
        )
        assert res["details"]["method"] == "tc"
        assert calls

    async def test_tc_latency_invalid_interface_raises(self, monkeypatch: pytest.MonkeyPatch):
        self._fake_linux_tc(monkeypatch, lambda *a, **k: None)
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.NETWORK_LATENCY, target="bad iface", duration_sec=0.01))
        assert "Invalid network interface" in res["error"]

    async def test_tc_latency_run_fails_simulates(self, monkeypatch: pytest.MonkeyPatch):
        def _boom(*a: object, **k: object) -> None:
            msg = "tc error"
            raise RuntimeError(msg)

        self._fake_linux_tc(monkeypatch, _boom)
        inj = FaultInjector()
        res = await inj.inject(FaultConfig(fault_type=FaultType.NETWORK_LATENCY, target="lo", duration_sec=0.01))
        assert res["details"]["simulated"] is True

    def test_recover_fault_tc_applied(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[Any] = []
        self._fake_linux_tc(monkeypatch, lambda *a, **k: calls.append(a))
        inj = FaultInjector()
        inj._recover_fault(
            {"config": {"fault_type": "network_latency", "target": "lo"}, "id": "n", "details": {"method": "tc", "target": "lo"}}
        )
        assert calls

    def test_recover_fault_tc_invalid(self, monkeypatch: pytest.MonkeyPatch):
        self._fake_linux_tc(monkeypatch, lambda *a, **k: None)
        inj = FaultInjector()
        with pytest.raises(ValueError, match="Invalid network interface"):
            inj._recover_fault(
                {
                    "config": {"fault_type": "network_latency", "target": "x"},
                    "id": "n",
                    "details": {"method": "tc", "target": "bad iface"},
                }
            )


class TestChaosEngineeringExperiment:
    def _patch_monitor(self, ce: ChaosEngineering, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fast_latency() -> float:
            return 5.0

        monkeypatch.setattr(ce._monitor, "_get_network_latency", _fast_latency)

    async def test_run_experiment_full_loop(self, monkeypatch: pytest.MonkeyPatch):
        ce = ChaosEngineering()
        self._patch_monitor(ce, monkeypatch)
        cfg = ExperimentConfig(
            name="full",
            hypothesis=ExperimentHypothesis(description="d", success_criteria=["all faults recover"]),
            faults=[
                FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01),
                FaultConfig(fault_type=FaultType.PROCESS_KILL, target="ghostproc", duration_sec=0.01),
            ],
            interval_between_faults_sec=0.01,
            recovery_timeout_sec=0.1,
        )
        res = await ce.run_experiment(cfg)
        assert res.status == ExperimentStatus.COMPLETED
        assert len(res.faults_injected) == 2
        assert len(res.faults_recovered) == 2
        assert len(res.metrics_during) == 2
        assert res.hypothesis_validated is True

    async def test_run_experiment_cancelled(self, monkeypatch: pytest.MonkeyPatch):
        ce = ChaosEngineering()

        async def _cancel() -> None:
            raise asyncio.CancelledError

        monkeypatch.setattr(ce._monitor, "start", _cancel)
        cfg = ExperimentConfig(name="c", hypothesis=ExperimentHypothesis(description="d"), faults=[])
        res = await ce.run_experiment(cfg)
        assert res.status == ExperimentStatus.ABORTED

    async def test_run_experiment_failure_rollback(self, monkeypatch: pytest.MonkeyPatch):
        ce = ChaosEngineering()

        async def _boom(config: FaultConfig) -> dict[str, Any]:
            msg = "inject boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(ce._injector, "inject", _boom)
        cfg = ExperimentConfig(
            name="fail",
            hypothesis=ExperimentHypothesis(description="d"),
            faults=[FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01)],
            rollback_on_failure=True,
        )
        res = await ce.run_experiment(cfg)
        assert res.status == ExperimentStatus.FAILED
        assert "inject boom" in res.errors[0]

    async def test_cancelled_experiment_removes_the_fill_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        def fills() -> list[Path]:
            return list(tmp_path.glob(".chaos_disk_fill_*.tmp"))

        _small_free_space(monkeypatch)
        ce = ChaosEngineering()
        self._patch_monitor(ce, monkeypatch)
        cfg = ExperimentConfig(
            name="cancel",
            hypothesis=ExperimentHypothesis(description="d"),
            faults=[FaultConfig(fault_type=FaultType.DISK_FILL, target=str(tmp_path), duration_sec=30)],
        )
        task = asyncio.create_task(ce.run_experiment(cfg))
        for _ in range(300):
            await asyncio.sleep(0.01)
            if fills():
                break
        assert fills(), "injection never created the fill file"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        [res] = ce.list_experiments()
        assert res.status == ExperimentStatus.ABORTED
        assert fills() == []
        faults = list(ce._injector.active_faults.values())
        assert faults, "the cancelled injection dropped its record, so nothing could recover it"
        assert all(f["recovered"] is True for f in faults)

    async def test_run_experiment_monitor_stop_fails(self, monkeypatch: pytest.MonkeyPatch):
        ce = ChaosEngineering()

        async def _boom(config: FaultConfig) -> dict[str, Any]:
            msg = "x"
            raise RuntimeError(msg)

        async def _stop_boom() -> list[SystemSnapshot]:
            msg = "stop boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(ce._injector, "inject", _boom)
        monkeypatch.setattr(ce._monitor, "stop", _stop_boom)
        cfg = ExperimentConfig(
            name="f2",
            hypothesis=ExperimentHypothesis(description="d"),
            faults=[FaultConfig(fault_type=FaultType.NETWORK_LATENCY, duration_sec=0.01)],
            rollback_on_failure=True,
        )
        res = await ce.run_experiment(cfg)
        assert res.status == ExperimentStatus.FAILED

    async def test_abort_experiment_running(self):
        ce = ChaosEngineering()
        cfg = ExperimentConfig(name="a", hypothesis=ExperimentHypothesis(description="d"))
        res = ExperimentResult(experiment_id="a1", config=cfg, status=ExperimentStatus.RUNNING)
        ce._experiments["a1"] = res
        assert await ce.abort_experiment("a1") is True
        assert res.status == ExperimentStatus.ABORTED

    async def test_abort_experiment_monitor_stop_fails(self, monkeypatch: pytest.MonkeyPatch):
        ce = ChaosEngineering()

        async def _stop_boom() -> list[SystemSnapshot]:
            msg = "stop"
            raise RuntimeError(msg)

        monkeypatch.setattr(ce._monitor, "stop", _stop_boom)
        cfg = ExperimentConfig(name="a", hypothesis=ExperimentHypothesis(description="d"))
        res = ExperimentResult(experiment_id="a2", config=cfg, status=ExperimentStatus.RUNNING)
        ce._experiments["a2"] = res
        assert await ce.abort_experiment("a2") is True

    def _completed_result(self, experiment_id: str = "exp") -> ExperimentResult:
        cfg = ExperimentConfig(
            name="done",
            hypothesis=ExperimentHypothesis(description="d"),
            faults=[FaultConfig(fault_type=FaultType.NETWORK_LATENCY)],
        )
        return ExperimentResult(
            experiment_id=experiment_id,
            config=cfg,
            status=ExperimentStatus.COMPLETED,
            start_time=100.0,
            end_time=200.0,
            metrics_before={"cpu": 30.0},
            metrics_after={"cpu": 33.0},
            faults_injected=[{"id": "f1"}],
            faults_recovered=[{"id": "f1"}],
            hypothesis_validated=True,
            resilience_score=0.9,
        )

    def test_export_report(self, tmp_path: Path):
        ce = ChaosEngineering()
        ce._experiments["exp"] = self._completed_result("exp")
        out = tmp_path / "nested" / "report.json"
        ce.export_report("exp", out)
        assert out.exists()
        assert '"experiment_id"' in out.read_text(encoding="utf-8")

    def test_resilience_summary_with_experiment(self):
        ce = ChaosEngineering()
        ce._experiments["exp"] = self._completed_result("exp")
        s = ce.get_resilience_summary()
        assert s["experiments_run"] == 1
        assert s["hypotheses_validated"] == 1
        assert s["total_faults_injected"] == 1
        assert s["avg_resilience"] == 0.9


class TestHypothesisAndScores:
    def _result(
        self,
        criteria: list[str],
        before: dict[str, float],
        after: dict[str, float],
        injected: int,
        recovered: int,
    ) -> ExperimentResult:
        cfg = ExperimentConfig(
            name="h",
            hypothesis=ExperimentHypothesis(description="d", success_criteria=criteria),
        )
        return ExperimentResult(
            experiment_id="h",
            config=cfg,
            status=ExperimentStatus.COMPLETED,
            metrics_before=before,
            metrics_after=after,
            faults_injected=[{"id": str(i)} for i in range(injected)],
            faults_recovered=[{"id": str(i)} for i in range(recovered)],
        )

    def test_cpu_over_threshold_fails(self):
        ce = ChaosEngineering()
        r = self._result(["cpu below 80"], {}, {"cpu": 90.0}, 0, 0)
        assert ce._validate_hypothesis(r) is False

    def test_cpu_under_threshold_passes(self):
        ce = ChaosEngineering()
        r = self._result(["cpu below 80"], {}, {"cpu": 70.0}, 0, 0)
        assert ce._validate_hypothesis(r) is True

    def test_memory_over_threshold_fails(self):
        ce = ChaosEngineering()
        r = self._result(["memory below 80"], {}, {"memory": 95.0}, 0, 0)
        assert ce._validate_hypothesis(r) is False

    def test_recover_incomplete_fails(self):
        ce = ChaosEngineering()
        r = self._result(["all faults recover"], {}, {}, 2, 1)
        assert ce._validate_hypothesis(r) is False

    def test_unparseable_threshold_skipped(self):
        ce = ChaosEngineering()
        r = self._result(["cpu below high"], {}, {"cpu": 99.0}, 0, 0)
        assert ce._validate_hypothesis(r) is True

    def test_unparseable_memory_threshold_skipped(self):
        ce = ChaosEngineering()
        r = self._result(["memory below high"], {}, {"memory": 99.0}, 0, 0)
        assert ce._validate_hypothesis(r) is True

    def test_resilience_score_with_faults(self):
        ce = ChaosEngineering()
        r = self._result([], {}, {}, 2, 1)
        assert ce._compute_resilience_score(r) == 0.7

    def test_steadiness_no_metrics(self):
        ce = ChaosEngineering()
        r = self._result([], {}, {}, 0, 0)
        assert ce._compute_steadiness(r) == 1.0


class TestExperimentMeasurement:
    """The scores only mean something if the baseline and the recovery window are real samples."""

    def _ce(self, monkeypatch: pytest.MonkeyPatch, sampler: Any) -> ChaosEngineering:
        ce = ChaosEngineering()
        ce._monitor._interval = 0.05
        monkeypatch.setattr(ce._monitor, "_collect_snapshot", sampler)

        async def _no_latency() -> float:
            return 0.0

        monkeypatch.setattr(ce._monitor, "_get_network_latency", _no_latency)
        return ce

    @staticmethod
    def _snapshot(cpu: float) -> SystemSnapshot:
        return SystemSnapshot(
            cpu_percent=cpu,
            memory_percent=cpu,
            disk_percent=cpu,
            processes_running=int(cpu),
            network_latency_ms=cpu,
            timestamp=time.time(),
        )

    async def test_metrics_before_is_an_actual_measurement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _steady() -> SystemSnapshot:
            return self._snapshot(25.0)

        ce = self._ce(monkeypatch, _steady)
        cfg = ExperimentConfig(name="baseline", hypothesis=ExperimentHypothesis(description="d"), faults=[])
        result = await ce.run_experiment(cfg)

        assert result.metrics_before["cpu"] == 25.0, f"the baseline collapsed to zeros: {result.metrics_before}"
        assert result.metrics_after["cpu"] == 25.0
        assert result.resilience_score == 1.0

    async def test_metrics_after_describes_only_the_recovery_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = {"faulted": True}

        async def _sample() -> SystemSnapshot:
            return self._snapshot(90.0 if state["faulted"] else 10.0)

        ce = self._ce(monkeypatch, _sample)
        real_recover_all = ce._injector.recover_all

        async def _recover_and_settle() -> None:
            await real_recover_all()
            state["faulted"] = False

        monkeypatch.setattr(ce._injector, "recover_all", _recover_and_settle)
        cfg = ExperimentConfig(name="window", hypothesis=ExperimentHypothesis(description="d"), faults=[])
        result = await ce.run_experiment(cfg)

        assert result.metrics_before["cpu"] == 90.0
        assert result.metrics_after["cpu"] == 10.0, "fault-phase samples are still averaged into 'after'"

    async def test_a_cpu_fault_window_ignores_a_backward_clock_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ce = ChaosEngineering()
        real_time = time.time
        reads = {"n": 0}

        def jumping() -> float:
            # The window is set on the first read; every later read answers 30 s in the past,
            # which is what an NTP correction does to a loop bounded by the wall clock.
            reads["n"] += 1
            return real_time() if reads["n"] == 1 else real_time() - 30.0

        monkeypatch.setattr(time, "time", jumping)
        await asyncio.wait_for(ce._injector._cpu_burn(cores=1, duration=0.05, fault_id="f"), timeout=1.5)
        assert reads["n"] == 0, "the fault window is still bounded by the wall clock"

    async def test_reported_duration_is_measured_on_the_monotonic_clock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ticks = chain(iter(range(0, 10_000_000, 3_600)), repeat(10_000_000.0))
        # chaos_engineering imports the same stdlib time module this test patches. The tail is an
        # infinite repeat: a finite iterator would run dry inside pytest's own timing and take the
        # whole run down with StopIteration.
        monkeypatch.setattr(time, "time", lambda: float(next(ticks)))

        async def _steady() -> SystemSnapshot:
            return self._snapshot(20.0)

        ce = self._ce(monkeypatch, _steady)
        cfg = ExperimentConfig(name="duration", hypothesis=ExperimentHypothesis(description="d"), faults=[])
        result = await ce.run_experiment(cfg)
        report = ce.generate_report(result.experiment_id)

        assert report["duration_sec"] < 60.0, f"duration came from a jumping wall clock: {report['duration_sec']}"
        assert result.end_time > result.start_time
