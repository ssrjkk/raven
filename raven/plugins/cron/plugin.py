from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from loguru import logger

PLUGIN_NAME = "cron"
PLUGIN_DESCRIPTION = "Schedule and manage recurring tasks using cron expressions"

_scheduler: AsyncIOScheduler | None = None
_callbacks: dict[str, Any] = {}


def _get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {"default": MemoryJobStore()}
        _scheduler = AsyncIOScheduler(jobstores=jobstores)
        _scheduler.start()
    return _scheduler


async def register_callback(name: str, callback) -> None:
    _callbacks[name] = callback


async def schedule(cron: str, task: str, task_id: str | None = None) -> str:
    """Schedule a task to run on a cron schedule. Args: cron (str): Cron expression (e.g. '0 9 * * *'), task (str): Description of task to run, task_id (str): Optional unique task ID"""
    scheduler = _get_scheduler()
    tid = task_id or f"cron_{hash(cron + task) % 100000}"

    async def run_task():
        logger.info("Cron trigger: {} running task: {}", tid, task)
        for name, cb in _callbacks.items():
            try:
                await cb("cron", "system", task)
            except Exception as e:
                logger.error("Cron task callback failed: {}", e)

    try:
        scheduler.add_job(
            run_task,
            CronTrigger.from_crontab(cron),
            id=tid,
            replace_existing=True,
            misfire_grace_time=60,
        )
        return f"Scheduled task '{tid}': '{task}' with cron '{cron}'"
    except Exception as e:
        logger.error("Cron schedule failed: {}", e)
        return f"Failed to schedule: {e}"


async def list_schedules() -> str:
    """List all active scheduled tasks"""
    scheduler = _get_scheduler()
    jobs = scheduler.get_jobs()
    if not jobs:
        return "No scheduled tasks."
    lines = []
    for job in jobs:
        trigger = str(job.trigger)
        next_run = job.next_run_time.isoformat() if job.next_run_time else "unknown"
        lines.append(f"- `{job.id}` | trigger: {trigger} | next: {next_run}")
    return "Scheduled tasks:\n" + "\n".join(lines)


async def cancel_schedule(task_id: str) -> str:
    """Cancel a scheduled task by its ID. Args: task_id (str): ID of the task to cancel"""
    scheduler = _get_scheduler()
    try:
        scheduler.remove_job(task_id)
        return f"Cancelled task: {task_id}"
    except Exception as e:
        logger.error("Cancel schedule failed: {}", e)
        return f"Failed to cancel: {e}"
