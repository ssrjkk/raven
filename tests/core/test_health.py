import asyncio

from raven.core.health import HealthRegistry


class TestHealthRegistry:
    def setup_method(self):
        self.reg = HealthRegistry()

    def test_register(self):
        async def check():
            return True

        self.reg.register("db", check)
        assert "db" in self.reg._checks

    async def test_check_all_ok(self):
        async def ok():
            return True

        self.reg.register("svc1", ok)
        self.reg.register("svc2", ok)
        result = await self.reg.check_all()
        assert result["status"] == "ok"
        assert len(result["checks"]) == 2

    async def test_check_all_degraded(self):
        async def ok():
            return True

        async def fail():
            return False

        self.reg.register("ok", ok)
        self.reg.register("fail", fail)
        result = await self.reg.check_all()
        assert result["status"] == "degraded"

    async def test_check_all_with_detail(self):
        async def detail():
            return "disk 90% full"

        self.reg.register("disk", detail)
        result = await self.reg.check_all()
        assert result["checks"]["disk"]["detail"] == "disk 90% full"

    async def test_check_all_timeout(self):
        async def slow():
            await asyncio.sleep(10)
            return True

        self.reg.register("slow", slow, timeout=0.01)
        result = await self.reg.check_all()
        assert result["checks"]["slow"]["ok"] is False
        assert result["checks"]["slow"]["detail"] == "timeout"

    async def test_check_all_exception(self):
        async def broken():
            raise RuntimeError("boom")

        self.reg.register("broken", broken)
        result = await self.reg.check_all()
        assert result["checks"]["broken"]["ok"] is False

    async def test_check_all_uses_cache(self):
        call_count = 0

        async def check():
            nonlocal call_count
            call_count += 1
            return True

        self.reg.register("svc", check)
        await self.reg.check_all()
        await self.reg.check_all()
        assert call_count == 1

    async def test_check_liveness(self):
        async def ok():
            return True

        self.reg.register("svc", ok)
        result = await self.reg.check_liveness()
        assert "status" in result

    async def test_check_readiness(self):
        async def ok():
            return True

        self.reg.register("svc", ok)
        result = await self.reg.check_readiness()
        assert result["status"] == "ok"

    async def test_check_readiness_skips_noncritical(self):
        async def ok():
            return True

        self.reg.register("noncrit", ok, critical=False)
        result = await self.reg.check_readiness()
        assert "noncrit" not in result["checks"]

    async def test_check_readiness_with_failure(self):
        async def fail():
            return False

        self.reg.register("crit", fail)
        result = await self.reg.check_readiness()
        assert result["status"] == "degraded"
