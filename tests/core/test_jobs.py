import asyncio

import pytest

from raven.core.jobs import Job, JobManager, JobStatus


class TestJob:
    def test_initial_state(self):
        async def fn():
            pass
        job = Job("test", fn)
        assert job.status == JobStatus.PENDING
        assert job.duration == 0.0

    def test_duration_before_run(self):
        async def fn():
            pass
        job = Job("test", fn)
        assert job.duration == 0.0

    async def test_run_success(self):
        results = []

        async def fn():
            results.append("done")
            return 42

        job = Job("test", fn)
        await job.run()
        assert job.status == JobStatus.COMPLETED
        assert job.result == 42

    async def test_run_failure(self):
        async def fn():
            raise ValueError("boom")

        job = Job("test", fn)
        await job.run()
        assert job.status == JobStatus.FAILED
        assert "boom" in job.error

    async def test_run_cancelled(self):
        async def fn():
            raise asyncio.CancelledError()

        job = Job("test", fn)
        await job.run()
        assert job.status == JobStatus.CANCELLED


class TestJobManager:
    def setup_method(self):
        self.mgr = JobManager()

    async def test_submit_and_complete(self):
        async def fn():
            return "result"

        job = await self.mgr.submit("test", fn)
        assert job.name == "test"
        await job._task
        assert job.status == JobStatus.COMPLETED

    async def test_submit_and_fail(self):
        async def fn():
            raise ValueError("fail")

        job = await self.mgr.submit("test", fn)
        await job._task
        assert job.status == JobStatus.FAILED

    async def test_get_job(self):
        async def fn():
            pass
        job = await self.mgr.submit("test", fn)
        assert self.mgr.get(job.id) is job
        assert self.mgr.get("nonexistent") is None

    async def test_cancel_job(self):
        async def fn():
            await asyncio.sleep(999)

        job = await self.mgr.submit("test", fn)
        assert await self.mgr.cancel(job.id) is True
        assert job.status == JobStatus.CANCELLED

    async def test_cancel_nonexistent(self):
        assert await self.mgr.cancel("nonexistent") is False

    async def test_list(self):
        async def fn():
            pass
        j1 = await self.mgr.submit("a", fn)
        j2 = await self.mgr.submit("b", fn)
        await j1._task
        await j2._task
        lst = self.mgr.list()
        assert len(lst) == 2

    async def test_list_filter_by_status(self):
        async def ok():
            pass

        async def fail():
            raise ValueError("x")

        j1 = await self.mgr.submit("ok", ok)
        j2 = await self.mgr.submit("fail", fail)
        await j1._task
        await j2._task
        completed = self.mgr.list(status="completed")
        assert len(completed) == 1
        failed = self.mgr.list(status="failed")
        assert len(failed) == 1

    async def test_list_limit(self):
        async def fn():
            pass
        for i in range(5):
            await self.mgr.submit(f"job-{i}", fn)
        assert len(self.mgr.list(limit=3)) == 3

    async def test_health_check(self):
        async def fn():
            pass
        await self.mgr.submit("ok", fn)
        h = await self.mgr.health_check()
        assert h["total"] == 1
        assert h["active"] == 0
