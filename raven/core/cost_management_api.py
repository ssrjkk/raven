from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from raven.core.cost_management import _cost


class UsageRequest(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    user_id: str = ""
    channel: str = ""
    session_id: str = ""


class PricingRequest(BaseModel):
    input_per_1k: float
    output_per_1k: float


class BudgetRequest(BaseModel):
    name: str
    daily_limit: float
    monthly_limit: float


def create_cost_management_router() -> APIRouter:
    router = APIRouter(prefix="/api/cost", tags=["cost"])

    @router.post("/usage")
    def record_usage(req: UsageRequest):
        rec = _cost.record_usage(req.model, req.input_tokens, req.output_tokens, req.user_id, req.channel, req.session_id)
        return {"id": rec.id, "model": rec.model, "input_tokens": rec.input_tokens, "output_tokens": rec.output_tokens, "cost": rec.cost}

    @router.get("/summary")
    def get_summary(hours: int = 24):
        return _cost.get_usage_summary(hours)

    @router.get("/pricing")
    def get_pricing():
        return {"pricing": _cost.get_model_pricing()}

    @router.put("/pricing/{model}")
    def set_pricing(model: str, req: PricingRequest):
        _cost.set_model_pricing(model, req.input_per_1k, req.output_per_1k)
        return {"ok": True, "model": model}

    @router.post("/budgets")
    def create_budget(req: BudgetRequest):
        budget = _cost.set_budget(req.name, req.daily_limit, req.monthly_limit)
        return {"id": budget.id, "name": budget.name, "daily_limit": budget.daily_limit, "monthly_limit": budget.monthly_limit}

    @router.get("/budgets")
    def list_budgets():
        budgets = _cost.get_budgets()
        return {"budgets": [{"id": b.id, "name": b.name, "daily_limit": b.daily_limit, "monthly_limit": b.monthly_limit, "current_daily": b.current_daily, "current_monthly": b.current_monthly} for b in budgets]}

    @router.delete("/budgets/{budget_id}")
    def delete_budget(budget_id: str):
        ok = _cost.delete_budget(budget_id)
        if not ok:
            raise HTTPException(404, f"Budget '{budget_id}' not found")
        return {"ok": True}

    @router.get("/check")
    def cost_check():
        return {
            "total_cost": round(_cost.get_total_cost(), 4),
            "daily_cost": round(_cost.get_daily_cost(), 4),
            "monthly_cost": round(_cost.get_monthly_cost(), 4),
            "budget_exceeded": _cost.is_budget_exceeded(),
        }

    return router
