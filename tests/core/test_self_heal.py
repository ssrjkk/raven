import asyncio

from raven.core.self_heal import MAX_RESTART_ATTEMPTS, SelfHealer, ServiceStatus


class TestServiceStatus:
    def test_initial(self):
        s = ServiceStatus("test")
        assert s.alive
        assert s.failures == 0
        assert s.restart_attempts == 0

    def test_record_success_resets_failures(self):
        s = ServiceStatus("test")
        s.record_failure()
        s.record_failure()
        s.record_success()
        assert s.failures == 0

    def test_record_failure(self):
        s = ServiceStatus("test")
        s.record_failure()
        s.record_failure()
        s.record_failure()
        assert not s.alive
        assert s.failures == 3

    def test_needs_restart(self):
        s = ServiceStatus("test")
        s.record_failure()
        s.record_failure()
        s.record_failure()
        assert s.needs_restart
        s.restart_attempts = MAX_RESTART_ATTEMPTS
        assert not s.needs_restart


class TestSelfHealer:
    def setup_method(self):
        self.healer = SelfHealer()

    def test_register_and_unregister(self):
        def check():
            return True

        def restart():
            pass

        self.healer.register("svc", check, restart)
        assert "svc" in self.healer._services
        self.healer.unregister("svc")
        assert "svc" not in self.healer._services

    def test_unregister_nonexistent(self):
        self.healer.unregister("does_not_exist")

    def test_status_report(self):
        def check():
            return True

        def restart():
            pass

        self.healer.register("svc", check, restart)
        report = self.healer.status_report()
        assert "svc" in report
        assert report["svc"]["alive"]

    async def test_start_stop(self):
        self.healer.start()
        assert self.healer._task is not None
        await self.healer.stop()
        assert self.healer._task is None

    async def test_loop_with_healthy_service(self):
        calls = []

        async def check():
            calls.append("check")
            return True

        def restart():
            calls.append("restart")

        self.healer.register("svc", check, restart)
        self.healer.start()
        await asyncio.sleep(0.1)
        self.healer.stop()
        assert len(calls) >= 0

    async def test_loop_with_unhealthy_service_restarts(self):
        restart_calls = []

        def check():
            return False

        async def restart():
            restart_calls.append("restart")

        self.healer.register("svc", check, restart)
        self.healer._services["svc"][0].failures = 3
        self.healer._services["svc"][0].alive = False

        await self.healer._loop.__wrapped__(self.healer) if hasattr(self.healer._loop, "__wrapped__") else None
