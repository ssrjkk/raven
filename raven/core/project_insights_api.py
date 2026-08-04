from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

from fastapi import APIRouter, Query
from loguru import logger

from raven.core.insights_api import _get_git, _get_git_log_async, _parse_log
from raven.core.project_metrics_api import _scan_code_stats

LINES_PER_HOUR = 250
MINUTES_SAVED_PER_COMMIT = 25
TOKENS_PER_AI_HOUR = 4000
COST_PER_TOKEN = 0.00001


class TrendPoint(TypedDict):
    date: str
    commits: int


class ProjectInsight(TypedDict):
    project_id: str
    time_saved_minutes: int
    ai_contribution_percent: float
    success_rate: float
    token_cost_estimate: float
    files: int
    code_lines: int
    commits: int
    active_days: int
    trend: list[TrendPoint]
    generated_at: str


def _count_reverts(commits: list[dict[str, Any]]) -> int:
    return sum(1 for c in commits if "revert" in (c.get("message") or "").lower())


def compute_project_insights(project_id: str, ws: Path, commits: list[dict[str, Any]], days: int) -> ProjectInsight:
    code_stats = _scan_code_stats(ws)
    total_code = sum(v["code"] for v in code_stats.values())
    total_files = sum(v["files"] for v in code_stats.values())

    per_day: dict[str, int] = {}
    for c in commits:
        day = str(c.get("date", ""))[:10]
        if day:
            per_day[day] = per_day.get(day, 0) + 1

    commits_count = len(commits)
    active_days = len(per_day)

    manual_hours = total_code / LINES_PER_HOUR
    ai_hours = commits_count * (MINUTES_SAVED_PER_COMMIT / 60) + active_days * 0.5
    ai_contribution = min(100.0, max(0.0, 100.0 * ai_hours / max(1.0, manual_hours)))
    time_saved_minutes = int(ai_hours * 0.6 * 60)

    revert_ratio = _count_reverts(commits) / max(commits_count, 1)
    success_rate = max(0.0, min(100.0, 100.0 * (1.0 - revert_ratio)))

    token_cost = ai_hours * TOKENS_PER_AI_HOUR * COST_PER_TOKEN

    today = datetime.now(UTC).date()
    trend: list[TrendPoint] = []
    for offset in range(days - 1, -1, -1):
        iso = (today - timedelta(days=offset)).isoformat()
        trend.append({"date": iso, "commits": per_day.get(iso, 0)})

    return ProjectInsight(
        project_id=project_id,
        time_saved_minutes=time_saved_minutes,
        ai_contribution_percent=round(ai_contribution, 1),
        success_rate=round(success_rate, 1),
        token_cost_estimate=round(token_cost, 4),
        files=total_files,
        code_lines=total_code,
        commits=commits_count,
        active_days=active_days,
        trend=trend,
        generated_at=datetime.now(UTC).isoformat(),
    )


def create_project_insights_router(workspace: str = "") -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects", tags=["projects"])
    ws = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    @router.get("/{project_id}/insights")
    async def project_insights(project_id: str, days: int = Query(30, ge=1, le=365)) -> ProjectInsight:
        git = _get_git(ws)
        commits: list[dict[str, Any]] = []
        if git:
            try:
                raw_log = await _get_git_log_async(git, days)
                commits = _parse_log(raw_log)
            except Exception as e:
                logger.debug("[insights] project git scan failed: {}", e)
        return compute_project_insights(project_id, ws, commits, days)

    return router
