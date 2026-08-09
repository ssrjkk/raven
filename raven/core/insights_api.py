from __future__ import annotations

import asyncio
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from loguru import logger

from raven.core.cost_management import _cost


def create_insights_router(workspace: str = "") -> APIRouter:
    router = APIRouter(prefix="/api/insights", tags=["insights"])
    ws = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    @router.get("/coding")
    async def coding_insights(days: int = Query(30, ge=1, le=365)):
        git = _get_git(ws)
        if not git:
            return {"error": "no git repo found", "commits_per_day": [], "top_files": [], "peak_hours": []}

        raw_log = await _get_git_log_async(git, days)
        if not raw_log:
            return {"commits_per_day": [], "top_files": [], "peak_hours": []}

        commits = _parse_log(raw_log)
        per_day: Counter[str] = Counter()
        per_hour: Counter[int] = Counter()
        per_file: Counter[str] = Counter()
        for c in commits:
            day = c["date"][:10]
            per_day[day] += 1
            try:
                hour = datetime.fromisoformat(c["date_iso"]).hour
                per_hour[hour] += 1
            except (ValueError, IndexError, KeyError):
                pass
            for f in c.get("files", []):
                per_file[f["path"]] += f.get("added", 0) + f.get("deleted", 0)

        return {
            "total_commits": len(commits),
            "total_days_active": len(per_day),
            "avg_commits_per_day": round(len(commits) / max(len(per_day), 1), 1),
            "commits_per_day": [{"date": d, "count": per_day[d]} for d in sorted(per_day)],
            "peak_hours": [{"hour": h, "count": per_hour[h]} for h in sorted(per_hour)],
            "top_files": [{"path": p, "changes": per_file[p]} for p, _ in per_file.most_common(20)],
        }

    @router.get("/llm")
    async def llm_insights(days: int = Query(30, ge=1, le=365)):
        cutoff = time.time() - days * 86400
        records = [r for r in _cost._records if r.timestamp >= cutoff]

        per_day: dict[str, dict[str, float]] = {}
        per_model: Counter[str] = Counter()
        per_hour: Counter[int] = Counter()
        total_cost = 0.0
        total_tokens = 0
        for r in records:
            day = datetime.fromtimestamp(r.timestamp, tz=UTC).strftime("%Y-%m-%d")
            if day not in per_day:
                per_day[day] = {"calls": 0.0, "cost": 0.0, "tokens": 0.0}
            per_day[day]["calls"] += 1
            per_day[day]["cost"] += r.cost
            per_day[day]["tokens"] += r.input_tokens + r.output_tokens
            per_model[r.model] += 1
            per_hour[datetime.fromtimestamp(r.timestamp, tz=UTC).hour] += 1
            total_cost += r.cost
            total_tokens += r.input_tokens + r.output_tokens

        return {
            "total_calls": len(records),
            "total_cost": round(total_cost, 4),
            "total_tokens": total_tokens,
            "avg_cost_per_call": round(total_cost / max(len(records), 1), 6),
            "calls_per_day": [{"date": d, **per_day[d]} for d in sorted(per_day)],
            "models": [
                {"model": m, "calls": per_model[m]} for m in sorted(per_model, key=lambda x: per_model[x], reverse=True)
            ],
            "peak_hours": [{"hour": h, "calls": per_hour[h]} for h in sorted(per_hour)],
        }

    @router.get("/workspace")
    async def workspace_insights():
        stats: dict[str, Any] = {
            "total_files": 0,
            "total_dirs": 0,
            "by_extension": {},
            "largest_files": [],
            "recently_modified": [],
        }
        try:
            exts: Counter[str] = Counter()
            sized: list[tuple[str, int]] = []
            modified: list[tuple[str, float]] = []
            for f in ws.rglob("*"):
                if f.is_file() and not f.name.startswith("."):
                    ext = f.suffix.lower() or "(no ext)"
                    exts[ext] += 1
                    try:
                        sz = f.stat().st_size
                        sized.append((str(f.relative_to(ws)), sz))
                        modified.append((str(f.relative_to(ws)), f.stat().st_mtime))
                    except OSError:
                        pass
                elif f.is_dir():
                    stats["total_dirs"] += 1
            stats["total_files"] = sum(exts.values())
            stats["by_extension"] = dict(exts.most_common(30))
            sized.sort(key=lambda x: -x[1])
            stats["largest_files"] = [{"path": p, "size_bytes": s} for p, s in sized[:20]]
            modified.sort(key=lambda x: -x[1])
            stats["recently_modified"] = [
                {"path": p, "modified_at": datetime.fromtimestamp(t, tz=UTC).isoformat()} for p, t in modified[:20]
            ]
        except OSError as e:
            logger.warning("[insights] workspace scan failed: {}", e)
        return stats

    return router


def _get_git(ws: Path) -> Any:
    try:
        from raven.coding.git_integration import GitIntegration

        g = GitIntegration()
        if ws != Path.cwd():
            g._repo = ws
        if not g.is_repo():
            return None
        return g
    except Exception as e:
        logger.debug("[insights] git integration unavailable: {}", e)
        return None


async def _get_git_log_async(git: Any, days: int) -> str:
    try:
        out = await asyncio.wait_for(
            asyncio.to_thread(
                git._run,
                "log",
                f"--since={days}.days.ago",
                "--format=%H|%h|%s|%an|%ae|%ad|%ai|%D",
                "--date=short",
                "--numstat",
            ),
            timeout=30,
        )
        return out[0] if isinstance(out, tuple) else str(out)
    except TimeoutError:
        logger.warning("[insights] git log timed out after 30s")
        return ""
    except Exception as e:
        logger.debug("[insights] git log failed: {}", e)
        return ""


def _parse_log(raw: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 8:
            if current:
                commits.append(current)
            current = {
                "hash": parts[1],
                "message": parts[2],
                "author": parts[3],
                "date": parts[5],
                "date_iso": parts[6],
                "files": [],
            }
        elif current is not None and "\t" in line:
            sp = line.split("\t")
            if len(sp) >= 3:
                added = 0
                deleted = 0
                try:
                    added = int(sp[0]) if sp[0] not in ("", "-") else 0
                    deleted = int(sp[1]) if sp[1] not in ("", "-") else 0
                except ValueError:
                    pass
                current["files"].append({"path": sp[2], "added": added, "deleted": deleted})
    if current:
        commits.append(current)
    return commits
