from __future__ import annotations

import contextlib

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.unique.chaos_engineering import (
    ChaosEngineering,
    ExperimentConfig,
    ExperimentHypothesis,
    FaultConfig,
    FaultType,
)

_ce: ChaosEngineering | None = None


def _get_ce() -> ChaosEngineering:
    global _ce
    if _ce is None:
        _ce = ChaosEngineering()
    return _ce


class InjectRequest(BaseModel):
    fault_type: str
    target: str = ""
    duration_sec: float = 30.0
    intensity: float = 0.5


class RecoverRequest(BaseModel):
    fault_id: str


class RunExperimentRequest(BaseModel):
    name: str
    faults_json: str
    hypothesis: str = ""


class ExperimentReportRequest(BaseModel):
    experiment_id: str


def create_chaos_router() -> APIRouter:
    router = APIRouter(prefix="/api/chaos", tags=["chaos"])

    @router.post("/inject")
    async def inject(req: InjectRequest):
        ce = _get_ce()
        try:
            ft = FaultType(req.fault_type)
        except ValueError as e:
            raise HTTPException(400, f"Unknown fault type '{req.fault_type}'") from e
        config = FaultConfig(fault_type=ft, target=req.target, duration_sec=req.duration_sec, intensity=req.intensity)
        try:
            result = await ce.injector.inject(config)
            return result
        except Exception as e:
            logger.error("Inject failed: {}", e)
            raise HTTPException(500, str(e)) from e

    @router.post("/recover")
    async def recover(req: RecoverRequest):
        ce = _get_ce()
        result = await ce.injector.recover(req.fault_id)
        if result is None:
            raise HTTPException(404, f"Fault '{req.fault_id}' not found")
        return result

    @router.post("/recover_all")
    async def recover_all():
        ce = _get_ce()
        results = await ce.injector.recover_all()
        return {"recovered": len(results)}

    @router.get("/active")
    async def list_active():
        ce = _get_ce()
        return {"active": list(ce.injector.active_faults.values())}

    @router.get("/history")
    async def list_history(fault_type: str = ""):
        ce = _get_ce()
        ft = None
        if fault_type:
            with contextlib.suppress(ValueError):
                ft = FaultType(fault_type)
        return {"history": ce.injector.get_history(ft)}

    @router.post("/experiments")
    async def run_experiment(req: RunExperimentRequest):
        ce = _get_ce()
        import json
        try:
            faults_data = json.loads(req.faults_json)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid faults JSON: {e}") from e
        fault_configs = []
        for f in faults_data:
            try:
                ft = FaultType(f["fault_type"])
            except (ValueError, KeyError) as e:
                raise HTTPException(400, f"Invalid fault_type: {f.get('fault_type', 'missing')}") from e
            fault_configs.append(FaultConfig(
                fault_type=ft,
                target=f.get("target", ""),
                duration_sec=f.get("duration_sec", 30.0),
                intensity=f.get("intensity", 0.5),
            ))
        hyp = ExperimentHypothesis(description=req.hypothesis or "No hypothesis specified")
        config = ExperimentConfig(name=req.name, hypothesis=hyp, faults=fault_configs)
        try:
            result = await ce.run_experiment(config)
            return {
                "experiment_id": result.experiment_id,
                "status": result.status.value,
                "resilience_score": result.resilience_score,
                "hypothesis_validated": result.hypothesis_validated,
                "faults_injected": len(result.faults_injected),
                "faults_recovered": len(result.faults_recovered),
            }
        except Exception as e:
            logger.error("Experiment failed: {}", e)
            raise HTTPException(500, str(e)) from e

    @router.get("/experiments")
    async def list_experiments():
        ce = _get_ce()
        return {"experiments": [e.config.name for e in ce.list_experiments()]}

    @router.get("/experiments/{experiment_id}")
    async def get_experiment(experiment_id: str):
        ce = _get_ce()
        result = ce.get_experiment(experiment_id)
        if not result:
            raise HTTPException(404, f"Experiment '{experiment_id}' not found")
        return {
            "experiment_id": result.experiment_id,
            "name": result.config.name,
            "status": result.status.value,
        }

    @router.get("/experiments/{experiment_id}/report")
    async def experiment_report(experiment_id: str):
        ce = _get_ce()
        try:
            return ce.generate_report(experiment_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e

    @router.get("/resilience/summary")
    async def resilience_summary():
        ce = _get_ce()
        return ce.get_resilience_summary()

    return router
