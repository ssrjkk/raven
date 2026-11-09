from __future__ import annotations

import asyncio
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

PLUGIN_NAME = "cron"
PLUGIN_DESCRIPTION = "Schedule and manage recurring tasks using cron expressions"

_scheduler: AsyncIOScheduler | None = None
_callbacks: dict[str, Any] = {}
_lock = asyncio.Lock()


def _get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {"default": MemoryJobStore()}
        _scheduler = AsyncIOScheduler(jobstores=jobstores)
        _scheduler.start()
    return _scheduler


def register_callback(name: str, callback) -> None:
    """Bind a host-side callable to cron triggers.

    Not a coroutine on purpose: a tool call carries JSON, so a model could only pass a string, and a
    string awaited as a callback breaks every later trigger. Host code registers a real coroutine.
    """
    _callbacks[name] = callback


async def schedule(cron: str, task: str, task_id: str | None = None) -> str:
    """Add a recurring job to this process's scheduler; the job only runs while the process stays up.

    cron: Five-field crontab expression, e.g. '0 9 * * *' for 09:00 every day.
    task: Text handed to the registered trigger callbacks; nothing happens if none is registered.
    task_id: Id to cancel this job under later. Empty derives one from the text, so the same schedule and task reuse it.
    """
    async with _lock:
        scheduler = _get_scheduler()
    tid = task_id or f"cron_{hash(cron + task) % 100000}"

    async def run_task():
        logger.info("Cron trigger: {} running task: {}", tid, task)
        for cb in _callbacks.values():
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
    async with _lock:
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
    """Remove a recurring job from this process's scheduler.

    task_id: The id shown by list_schedules or passed to schedule. An unknown id is reported as a failure.
    """
    async with _lock:
        scheduler = _get_scheduler()
    try:
        scheduler.remove_job(task_id)
        return f"Cancelled task: {task_id}"
    except Exception as e:
        logger.error("Cancel schedule failed: {}", e)
        return f"Failed to cancel: {e}"
