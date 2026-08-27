from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from loguru import logger


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job:
    def __init__(self, name: str, fn: Callable[..., Awaitable[Any]], *args, **kwargs):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.status = JobStatus.PENDING
        self.result: Any = None
        self.error: str | None = None
        self.created_at = time.monotonic()
        self.started_at: float = 0.0
        self.finished_at: float = 0.0
        self._task: asyncio.Task[None] | None = None

    @property
    def duration(self) -> float:
        if self.finished_at and self.started_at:
            return self.finished_at - self.started_at
        return 0.0

    async def run(self):
        self.status = JobStatus.RUNNING
        self.started_at = time.monotonic()
        try:
            self.result = await self._fn(*self._args, **self._kwargs)
            self.status = JobStatus.COMPLETED
        except asyncio.CancelledError:
            self.status = JobStatus.CANCELLED
            self.error = "Cancelled"
            raise
        except Exception as e:
            self.status = JobStatus.FAILED
            self.error = str(e)
        finally:
            self.finished_at = time.monotonic()


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def submit(self, name: str, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Job:
        job = Job(name, fn, *args, **kwargs)
        async with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > 200:
                done_ids = [
                    jid for jid, j in self._jobs.items()
                    if j.status.value in ("completed", "failed", "cancelled") and j.finished_at
                ]
                for jid in sorted(done_ids, key=lambda jid: self._jobs[jid].finished_at or 0)[:100]:
                    del self._jobs[jid]
        job._task = asyncio.create_task(self._run_job(job))
        return job

    async def _run_job(self, job: Job):
        await job.run()
        logger.info("[jobs] {} ({}) → {}", job.name, job.id, job.status.value)

    async def cancel(self, job_id: str) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job and job._task and not job._task.done():
                job._task.cancel()
                return True
        return False

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        result = []
        for job in sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True):
            if status and job.status.value != status:
                continue
            result.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "status": job.status.value,
                    "duration": round(job.duration, 3),
                    "error": job.error,
                }
            )
            if len(result) >= limit:
                break
        return result

    async def health_check(self) -> dict[str, Any]:
        async with self._lock:
            active = sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)
            failed = sum(1 for j in self._jobs.values() if j.status == JobStatus.FAILED)
            total = len(self._jobs)
        return {"total": total, "active": active, "failed": failed}


job_manager = JobManager()
