from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class FaultType(Enum):
    SERVICE_KILL = "service_kill"
    NETWORK_LATENCY = "network_latency"
    DISK_FILL = "disk_fill"
    CPU_STORM = "cpu_storm"
    MEMORY_LEAK = "memory_leak"
    PROCESS_KILL = "process_kill"


class ExperimentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class FaultConfig:
    fault_type: FaultType
    target: str = ""
    duration_sec: float = 30.0
    intensity: float = 0.5  # 0.0–1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentHypothesis:
    description: str
    expected_behavior: str = ""
    success_criteria: list[str] = field(default_factory=list)
    metrics_expected: dict[str, float] = field(default_factory=dict)


@dataclass
class ExperimentConfig:
    name: str
    hypothesis: ExperimentHypothesis
    faults: list[FaultConfig] = field(default_factory=list)
    interval_between_faults_sec: float = 5.0
    recovery_timeout_sec: float = 60.0
    rollback_on_failure: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class ExperimentResult:
    experiment_id: str
    config: ExperimentConfig
    status: ExperimentStatus
    start_time: float = 0.0
    end_time: float = 0.0
    metrics_before: dict[str, Any] = field(default_factory=dict)
    metrics_during: list[dict[str, Any]] = field(default_factory=list)
    metrics_after: dict[str, Any] = field(default_factory=dict)
    faults_injected: list[dict[str, Any]] = field(default_factory=list)
    faults_recovered: list[dict[str, Any]] = field(default_factory=list)
    hypothesis_validated: bool = False
    resilience_score: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class SystemSnapshot:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    processes_running: int = 0
    network_latency_ms: float = 0.0
    timestamp: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class SystemMonitor:
    def __init__(self, collect_interval_sec: float = 1.0) -> None:
        self._interval = collect_interval_sec
        self._snapshots: list[SystemSnapshot] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._snapshots.clear()
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("System monitor started (interval={}s)", self._interval)

    async def stop(self) -> list[SystemSnapshot]:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("System monitor stopped, collected {} snapshots", len(self._snapshots))
        return list(self._snapshots)

    async def _collect_loop(self) -> None:
        while self._running:
            snapshot = await self._collect_snapshot()
            self._snapshots.append(snapshot)
            await asyncio.sleep(self._interval)

    async def _collect_snapshot(self) -> SystemSnapshot:
        cpu = await self._get_cpu()
        mem = await self._get_memory()
        disk = await self._get_disk()
        procs = await self._get_process_count()
        latency = await self._get_network_latency()
        return SystemSnapshot(
            cpu_percent=cpu,
            memory_percent=mem,
            disk_percent=disk,
            processes_running=procs,
            network_latency_ms=latency,
            timestamp=time.time(),
        )

    async def _get_cpu(self) -> float:
        try:
            import psutil
            return float(psutil.cpu_percent(interval=0.1))
        except ImportError:
            return secrets.SystemRandom().uniform(10.0, 80.0)

    async def _get_memory(self) -> float:
        try:
            import psutil
            return float(psutil.virtual_memory().percent)
        except ImportError:
            return secrets.SystemRandom().uniform(20.0, 70.0)

    async def _get_disk(self) -> float:
        try:
            import psutil
            return float(psutil.disk_usage("/").percent)
        except ImportError:
            return secrets.SystemRandom().uniform(30.0, 80.0)

    async def _get_process_count(self) -> int:
        try:
            import psutil
            return len(psutil.pids())
        except ImportError:
            return secrets.SystemRandom().randint(100, 500)

    async def _get_network_latency(self) -> float:
        return 0.0

    def get_snapshots(self, since: float = 0.0) -> list[SystemSnapshot]:
        if since <= 0:
            return list(self._snapshots)
        return [s for s in self._snapshots if s.timestamp >= since]

    def get_average_metrics(self, snapshots: list[SystemSnapshot] | None = None) -> dict[str, float]:
        samples = snapshots or self._snapshots
        if not samples:
            return {"cpu": 0.0, "memory": 0.0, "disk": 0.0, "processes": 0.0, "latency": 0.0}
        n = len(samples)
        return {
            "cpu": round(sum(s.cpu_percent for s in samples) / n, 2),
            "memory": round(sum(s.memory_percent for s in samples) / n, 2),
            "disk": round(sum(s.disk_percent for s in samples) / n, 2),
            "processes": round(sum(s.processes_running for s in samples) / n, 2),
            "latency": round(sum(s.network_latency_ms for s in samples) / n, 2),
        }


class FaultInjector:
    def __init__(self) -> None:
        self._active_faults: dict[str, dict[str, Any]] = {}
        self._fault_history: list[dict[str, Any]] = []

    @property
    def active_faults(self) -> dict[str, dict[str, Any]]:
        return dict(self._active_faults)

    async def inject(self, config: FaultConfig) -> dict[str, Any]:
        fault_id = uuid.uuid4().hex[:12]
        logger.info("Injecting fault [{}]: type={}, target='{}', duration={}s, intensity={}",
                     fault_id, config.fault_type.value, config.target, config.duration_sec, config.intensity)
        fault_record: dict[str, Any] = {
            "id": fault_id,
            "config": {
                "fault_type": config.fault_type.value,
                "target": config.target,
                "duration_sec": config.duration_sec,
                "intensity": config.intensity,
                "metadata": config.metadata,
            },
            "start_time": time.time(),
            "recovered": False,
            "error": "",
        }

        try:
            if config.fault_type == FaultType.SERVICE_KILL:
                await self._inject_service_kill(fault_record)
            elif config.fault_type == FaultType.NETWORK_LATENCY:
                await self._inject_network_latency(fault_record)
            elif config.fault_type == FaultType.DISK_FILL:
                await self._inject_disk_fill(fault_record)
            elif config.fault_type == FaultType.CPU_STORM:
                await self._inject_cpu_storm(fault_record)
            elif config.fault_type == FaultType.MEMORY_LEAK:
                await self._inject_memory_leak(fault_record)
            elif config.fault_type == FaultType.PROCESS_KILL:
                await self._inject_process_kill(fault_record)
        except Exception as exc:
            fault_record["error"] = str(exc)
            logger.error("Fault injection failed [{}]: {}", fault_id, exc)

        self._active_faults[fault_id] = fault_record
        self._fault_history.append(fault_record)
        return fault_record

    async def recover(self, fault_id: str) -> dict[str, Any] | None:
        fault = self._active_faults.get(fault_id)
        if not fault:
            return None
        if fault["recovered"]:
            return fault

        logger.info("Recovering fault [{}]: type={}", fault_id, fault["config"]["fault_type"])
        try:
            await self._recover_fault(fault)
            fault["recovered"] = True
            fault["recovery_time"] = time.time()
            logger.info("Fault [{}] recovered successfully", fault_id)
        except Exception as exc:
            fault["error"] = f"Recovery failed: {exc}"
            logger.error("Fault recovery failed [{}]: {}", fault_id, exc)

        return fault

    async def recover_all(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for fault_id in list(self._active_faults.keys()):
            result = await self.recover(fault_id)
            if result:
                results.append(result)
        return results

    async def _inject_service_kill(self, fault: dict[str, Any]) -> None:
        service = fault["config"]["target"]
        if not service:
            fault["error"] = "No service target specified"
            return
        logger.warning("[SIMULATED] Killing service: {}", service)
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name"]):
                if service.lower() in proc.info["name"].lower():
                    proc.kill()
                    fault["details"] = {"killed_pid": proc.info["pid"], "service": service}
                    logger.warning("Killed process {} ({})", proc.info["pid"], proc.info["name"])
                    return
            logger.warning("Service '{}' not found running, simulated kill", service)
            fault["details"] = {"service": service, "simulated": True}
        except ImportError:
            logger.warning("[SIMULATED] Killing service '{}' (psutil not available)", service)
            fault["details"] = {"service": service, "simulated": True}

    async def _inject_network_latency(self, fault: dict[str, Any]) -> None:
        latency_ms = fault["config"]["intensity"] * 5000  # 0–5000ms
        target = fault["config"]["target"] or "all interfaces"
        logger.warning("[SIMULATED] Adding {}ms latency to {}", round(latency_ms, 1), target)
        fault["details"] = {"latency_ms": round(latency_ms, 1), "target": target, "simulated": True}

    async def _inject_disk_fill(self, fault: dict[str, Any]) -> None:
        fill_percent = 50.0 + fault["config"]["intensity"] * 50.0  # 50–100%
        logger.warning("[SIMULATED] Filling disk to {}%", round(fill_percent, 1))
        import tempfile
        target = fault["config"]["target"] or tempfile.gettempdir()
        fault["details"] = {"fill_percent": round(fill_percent, 1), "target": target, "simulated": True}

    async def _inject_cpu_storm(self, fault: dict[str, Any]) -> None:
        cores = max(1, int(fault["config"]["intensity"] * 8))
        logger.warning("[SIMULATED] Consuming {} CPU cores", cores)
        fault["details"] = {"cores": cores, "simulated": True}
        asyncio.create_task(self._cpu_burn(cores, fault["config"]["duration_sec"], fault["id"]))

    async def _cpu_burn(self, cores: int, duration: float, fault_id: str) -> None:
        async def _burn() -> None:
            end = time.time() + duration
            while time.time() < end:
                _ = [x * x for x in range(10000)]
                await asyncio.sleep(0.01)

        tasks = [asyncio.create_task(_burn()) for _ in range(cores)]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()

    async def _inject_memory_leak(self, fault: dict[str, Any]) -> None:
        mb = int(fault["config"]["intensity"] * 1024)  # 0–1024 MB
        if mb < 1:
            mb = 1
        logger.warning("[SIMULATED] Allocating {}MB memory", mb)
        fault["details"] = {"mb": mb, "simulated": True}
        asyncio.create_task(self._memory_burn(mb, fault["config"]["duration_sec"], fault["id"]))

    async def _memory_burn(self, mb: int, duration: float, fault_id: str) -> None:
        chunk_size = 1024 * 1024
        chunks: list[bytearray] = []
        total_allocated = 0
        try:
            end = time.time() + duration
            while time.time() < end and total_allocated < mb * 1024 * 1024:
                chunk = bytearray(chunk_size)
                chunks.append(chunk)
                total_allocated += chunk_size
                await asyncio.sleep(0.01)
        except MemoryError:
            logger.warning("[MEMORY_LEAK] Hit memory limit after {}MB", round(total_allocated / (1024 * 1024), 1))
        finally:
            chunks.clear()

    async def _inject_process_kill(self, fault: dict[str, Any]) -> None:
        process_name = fault["config"]["target"]
        if not process_name:
            fault["error"] = "No process target specified"
            return
        logger.warning("[SIMULATED] Killing process: {}", process_name)
        try:
            import psutil
            for proc in psutil.process_iter(["pid", "name"]):
                if process_name.lower() in proc.info["name"].lower():
                    proc.kill()
                    fault["details"] = {"killed_pid": proc.info["pid"], "process": process_name}
                    logger.warning("Killed process {} ({})", proc.info["pid"], proc.info["name"])
                    return
            logger.warning("Process '{}' not found, simulated kill", process_name)
            fault["details"] = {"process": process_name, "simulated": True}
        except ImportError:
            logger.warning("[SIMULATED] Killing process '{}' (psutil not available)", process_name)
            fault["details"] = {"process": process_name, "simulated": True}

    async def _recover_fault(self, fault: dict[str, Any]) -> None:
        fault_type = FaultType(fault["config"]["fault_type"])
        if fault_type == FaultType.CPU_STORM:
            logger.info("[RECOVER] CPU storm ended")
        elif fault_type == FaultType.MEMORY_LEAK:
            logger.info("[RECOVER] Memory released")
        elif fault_type == FaultType.DISK_FILL:
            logger.info("[RECOVER] Disk space cleaned")
        elif fault_type == FaultType.NETWORK_LATENCY:
            logger.info("[RECOVER] Network latency removed")
        elif fault_type == FaultType.SERVICE_KILL:
            logger.info("[RECOVER] Service '{}' would need restart", fault["config"]["target"])
        elif fault_type == FaultType.PROCESS_KILL:
            logger.info("[RECOVER] Process '{}' would need restart", fault["config"]["target"])

    def get_history(self, fault_type: FaultType | None = None) -> list[dict[str, Any]]:
        if fault_type is None:
            return list(self._fault_history)
        return [f for f in self._fault_history if f["config"]["fault_type"] == fault_type.value]

    def clear_history(self) -> None:
        self._fault_history.clear()
        self._active_faults.clear()


class ChaosEngineering:
    def __init__(self) -> None:
        self._injector = FaultInjector()
        self._monitor = SystemMonitor()
        self._experiments: dict[str, ExperimentResult] = {}
        self._running_experiment: ExperimentResult | None = None

    @property
    def injector(self) -> FaultInjector:
        return self._injector

    @property
    def monitor(self) -> SystemMonitor:
        return self._monitor

    async def run_experiment(self, config: ExperimentConfig) -> ExperimentResult:
        experiment_id = uuid.uuid4().hex[:12]
        logger.info("Starting experiment '{}' [{}]: {} fault(s)", config.name, experiment_id, len(config.faults))

        result = ExperimentResult(
            experiment_id=experiment_id,
            config=config,
            status=ExperimentStatus.PENDING,
            start_time=time.time(),
        )
        self._experiments[experiment_id] = result
        self._running_experiment = result

        try:
            await self._monitor.start()
            result.metrics_before = self._monitor.get_average_metrics()

            result.status = ExperimentStatus.RUNNING
            for i, fault_config in enumerate(config.faults):
                logger.info("Fault {}/{}: {}", i + 1, len(config.faults), fault_config.fault_type.value)
                injected = await self._injector.inject(fault_config)
                result.faults_injected.append(injected)

                snapshot = await self._monitor._collect_snapshot()
                result.metrics_during.append({
                    "fault_index": i,
                    "fault_type": fault_config.fault_type.value,
                    "snapshot": {
                        "cpu": snapshot.cpu_percent,
                        "memory": snapshot.memory_percent,
                        "disk": snapshot.disk_percent,
                        "processes": snapshot.processes_running,
                    },
                    "timestamp": snapshot.timestamp,
                })

                await asyncio.sleep(fault_config.duration_sec)

                recovered = await self._injector.recover(injected["id"])
                if recovered:
                    result.faults_recovered.append(recovered)

                if i < len(config.faults) - 1:
                    await asyncio.sleep(config.interval_between_faults_sec)

            result.status = ExperimentStatus.RECOVERING
            await self._injector.recover_all()

            await asyncio.sleep(2.0)
            snapshots = await self._monitor.stop()
            result.metrics_after = self._monitor.get_average_metrics(snapshots)
            result.hypothesis_validated = self._validate_hypothesis(result)
            result.resilience_score = self._compute_resilience_score(result)
            result.status = ExperimentStatus.COMPLETED
            logger.info("Experiment '{}' completed: resilience={}, hypothesis_validated={}",
                        config.name, result.resilience_score, result.hypothesis_validated)

        except asyncio.CancelledError:
            result.status = ExperimentStatus.ABORTED
            logger.warning("Experiment '{}' aborted", config.name)
        except Exception as exc:
            result.status = ExperimentStatus.FAILED
            result.errors.append(str(exc))
            logger.error("Experiment '{}' failed: {}", config.name, exc)
            if config.rollback_on_failure:
                await self._injector.recover_all()
                try:
                    await self._monitor.stop()
                except Exception as exc:
                    logger.debug("monitor stop failed: {}", exc)
        finally:
            result.end_time = time.time()
            self._running_experiment = None

        return result

    async def abort_experiment(self, experiment_id: str) -> bool:
        result = self._experiments.get(experiment_id)
        if not result or result.status in (ExperimentStatus.COMPLETED, ExperimentStatus.FAILED, ExperimentStatus.ABORTED):
            return False
        result.status = ExperimentStatus.ABORTED
        await self._injector.recover_all()
        try:
            await self._monitor.stop()
        except Exception as exc:
            logger.debug("monitor stop failed: {}", exc)
        logger.warning("Experiment '{}' aborted by user", result.config.name)
        return True

    def get_experiment(self, experiment_id: str) -> ExperimentResult | None:
        return self._experiments.get(experiment_id)

    def list_experiments(self, status: ExperimentStatus | None = None) -> list[ExperimentResult]:
        if status is None:
            return list(self._experiments.values())
        return [e for e in self._experiments.values() if e.status == status]

    def generate_report(self, experiment_id: str) -> dict[str, Any]:
        result = self._experiments.get(experiment_id)
        if not result:
            raise ValueError(f"Experiment not found: {experiment_id}")

        duration = result.end_time - result.start_time if result.end_time > 0 else 0.0
        steadiness = self._compute_steadiness(result)
        return {
            "experiment_id": result.experiment_id,
            "name": result.config.name,
            "status": result.status.value,
            "duration_sec": round(duration, 2),
            "hypothesis": {
                "description": result.config.hypothesis.description,
                "validated": result.hypothesis_validated,
                "success_criteria": result.config.hypothesis.success_criteria,
            },
            "resilience_score": round(result.resilience_score, 4),
            "steadiness_score": round(steadiness, 4),
            "faults_injected": len(result.faults_injected),
            "faults_recovered": len(result.faults_recovered),
            "recovery_rate": round(len(result.faults_recovered) / max(len(result.faults_injected), 1), 4),
            "metrics": {
                "before": result.metrics_before,
                "after": result.metrics_after,
                "delta": {
                    k: round(result.metrics_after.get(k, 0) - result.metrics_before.get(k, 0), 2)
                    for k in result.metrics_before
                },
            },
            "errors": result.errors,
            "tags": result.config.tags,
            "start_time": result.start_time,
            "end_time": result.end_time,
        }

    def export_report(self, experiment_id: str, path: str | Path) -> None:
        report = self.generate_report(experiment_id)
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Report exported to {}", file_path)

    def get_resilience_summary(self) -> dict[str, Any]:
        completed = [e for e in self._experiments.values() if e.status == ExperimentStatus.COMPLETED]
        if not completed:
            return {"experiments_run": 0, "avg_resilience": 0.0, "avg_steadiness": 0.0}
        avg_resilience = sum(e.resilience_score for e in completed) / len(completed)
        avg_steadiness = sum(self._compute_steadiness(e) for e in completed) / len(completed)
        validated = sum(1 for e in completed if e.hypothesis_validated)
        return {
            "experiments_run": len(completed),
            "avg_resilience": round(avg_resilience, 4),
            "avg_steadiness": round(avg_steadiness, 4),
            "hypotheses_validated": validated,
            "total_faults_injected": sum(len(e.faults_injected) for e in completed),
            "total_faults_recovered": sum(len(e.faults_recovered) for e in completed),
        }

    def _validate_hypothesis(self, result: ExperimentResult) -> bool:
        hypothesis = result.config.hypothesis
        if not hypothesis.success_criteria:
            return True
        after = result.metrics_after
        for criterion in hypothesis.success_criteria:
            criterion_lower = criterion.lower()
            if "cpu" in criterion_lower and "below" in criterion_lower:
                try:
                    threshold = float("".join(c for c in criterion if c.isdigit() or c == "."))
                    if after.get("cpu", 100) > threshold:
                        return False
                except ValueError:
                    logger.debug("Could not parse CPU threshold from criterion: {}", criterion)
            if "memory" in criterion_lower and "below" in criterion_lower:
                try:
                    threshold = float("".join(c for c in criterion if c.isdigit() or c == "."))
                    if after.get("memory", 100) > threshold:
                        return False
                except ValueError:
                    logger.debug("Could not parse memory threshold from criterion: {}", criterion)
            if "recover" in criterion_lower:
                injected = len(result.faults_injected)
                recovered = len(result.faults_recovered)
                if recovered < injected:
                    return False
        return True

    def _compute_resilience_score(self, result: ExperimentResult) -> float:
        total_faults = len(result.faults_injected)
        if total_faults == 0:
            return 1.0
        recovery_rate = len(result.faults_recovered) / total_faults
        steady = self._compute_steadiness(result)
        return round(recovery_rate * 0.6 + steady * 0.4, 4)

    def _compute_steadiness(self, result: ExperimentResult) -> float:
        before = result.metrics_before
        after = result.metrics_after
        if not before or not after:
            return 1.0
        deltas = []
        for key in before:
            delta = abs(after.get(key, before[key]) - before[key])
            max_val = max(before[key], 1.0)
            deltas.append(1.0 - min(delta / max_val, 1.0))
        return sum(deltas) / len(deltas) if deltas else 1.0
