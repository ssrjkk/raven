from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from raven.core.ab_testing import _engine


class CreateRequest(BaseModel):
    name: str
    description: str
    variants_json: str
    metric_name: str = "conversion"


class UpdateRequest(BaseModel):
    status: str = ""


class RecordRequest(BaseModel):
    variant: str
    metric_name: str = "conversion"
    value: float = 1.0
    user_id: str = ""


def create_ab_testing_router() -> APIRouter:
    router = APIRouter(prefix="/api/ab", tags=["ab_testing"])

    @router.post("/experiments")
    def create_experiment(req: CreateRequest):
        try:
            variants = json.loads(req.variants_json)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid variants JSON: {e}") from e
        if len(variants) < 2:
            raise HTTPException(400, "At least 2 variants required")
        exp = _engine.create_experiment(req.name, req.description, variants, req.metric_name)
        return {
            "id": exp.id,
            "name": exp.name,
            "status": exp.status,
            "variants": [{"name": v.name, "weight": v.weight} for v in exp.variants],
            "metric": exp.metric_name,
        }

    @router.get("/experiments")
    def list_experiments():
        experiments = _engine.list_experiments()
        return {
            "experiments": [
                {
                    "id": e.id,
                    "name": e.name,
                    "status": e.status,
                    "variants": [{"name": v.name, "weight": v.weight} for v in e.variants],
                    "metric": e.metric_name,
                    "created_at": e.created_at,
                }
                for e in experiments
            ]
        }

    @router.get("/experiments/{experiment_id}")
    def get_experiment(experiment_id: str):
        exp = _engine.get_experiment(experiment_id)
        if not exp:
            raise HTTPException(404, f"Experiment '{experiment_id}' not found")
        return {
            "id": exp.id,
            "name": exp.name,
            "description": exp.description,
            "status": exp.status,
            "variants": [{"name": v.name, "weight": v.weight, "config": v.config} for v in exp.variants],
            "metric": exp.metric_name,
            "created_at": exp.created_at,
            "updated_at": exp.updated_at,
        }

    @router.post("/experiments/{experiment_id}/status")
    def update_status(experiment_id: str, req: UpdateRequest):
        action = req.status
        actions = {
            "running": _engine.start_experiment,
            "paused": _engine.pause_experiment,
            "completed": _engine.complete_experiment,
        }
        fn = actions.get(action)
        if not fn:
            raise HTTPException(400, f"Invalid status '{action}'. Valid: running, paused, completed")
        exp = fn(experiment_id)
        if not exp:
            raise HTTPException(404, f"Experiment '{experiment_id}' not found")
        return {"id": exp.id, "status": exp.status}

    @router.delete("/experiments/{experiment_id}")
    def delete_experiment(experiment_id: str):
        ok = _engine.delete_experiment(experiment_id)
        if not ok:
            raise HTTPException(404, f"Experiment '{experiment_id}' not found")
        return {"ok": True}

    @router.post("/experiments/{experiment_id}/assign")
    def assign_variant(experiment_id: str, body: dict[str, str] | None = None):
        body = body or {}
        variant = _engine.assign_variant(experiment_id, body.get("user_id", ""))
        if variant is None:
            raise HTTPException(400, f"Experiment '{experiment_id}' not found or not running")
        return {"variant": variant}

    @router.post("/experiments/{experiment_id}/record")
    def record_event(experiment_id: str, req: RecordRequest):
        exp = _engine.get_experiment(experiment_id)
        if not exp:
            raise HTTPException(404, f"Experiment '{experiment_id}' not found")
        _engine.record_event(experiment_id, req.variant, req.metric_name, req.value, req.user_id)
        return {"ok": True}

    @router.get("/experiments/{experiment_id}/results")
    def get_results(experiment_id: str):
        results = _engine.get_results(experiment_id)
        if not results:
            raise HTTPException(404, f"Experiment '{experiment_id}' not found")
        return results

    return router
