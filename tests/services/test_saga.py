import pytest

from services.observability_sdk.saga import Saga, SagaError


class TestSaga:
    @pytest.mark.asyncio
    async def test_successful_saga(self):
        saga = Saga(saga_id="test-ok")
        executed: list[str] = []

        async def step1():
            executed.append("step1")
            return "result1"

        async def step2():
            executed.append("step2")
            return "result2"

        async def noop():
            pass

        saga.add_step("step1", step1, noop)
        saga.add_step("step2", step2, noop)

        results = await saga.execute()
        assert results == {"step1": "result1", "step2": "result2"}
        assert executed == ["step1", "step2"]

    @pytest.mark.asyncio
    async def test_compensation_on_failure(self):
        saga = Saga(saga_id="test-comp")
        executed: list[str] = []
        compensated: list[str] = []

        async def step1():
            executed.append("step1")

        async def comp1():
            compensated.append("comp1")

        async def step2():
            executed.append("step2")
            raise RuntimeError("step2 failed")

        async def comp2():
            compensated.append("comp2")

        saga.add_step("step1", step1, comp1)
        saga.add_step("step2", step2, comp2)

        with pytest.raises(SagaError) as exc:
            await saga.execute()

        assert "step2" in str(exc.value)
        assert executed == ["step1", "step2"]
        assert compensated == ["comp1"]

    @pytest.mark.asyncio
    async def test_all_steps_compensated_if_mid_failure(self):
        saga = Saga(saga_id="test-mid")
        compensated: list[str] = []

        async def a():
            pass

        async def ca():
            compensated.append("ca")

        async def b():
            pass

        async def cb():
            compensated.append("cb")

        async def c():
            raise ValueError("c failed")

        async def cc():
            compensated.append("cc")

        saga.add_step("a", a, ca)
        saga.add_step("b", b, cb)
        saga.add_step("c", c, cc)

        with pytest.raises(SagaError):
            await saga.execute()

        assert compensated == ["cb", "ca"]

    @pytest.mark.asyncio
    async def test_compensation_failure_logged(self, caplog):
        saga = Saga(saga_id="test-log")
        executed: list[str] = []
        compensated: list[str] = []

        async def step1():
            executed.append("s1")

        async def bad_comp():
            compensated.append("bad")
            raise RuntimeError("compensation failed")

        async def step2():
            executed.append("s2")
            raise RuntimeError("step2 failed")

        async def comp2():
            compensated.append("c2")

        saga.add_step("step1", step1, bad_comp)
        saga.add_step("step2", step2, comp2)

        with pytest.raises(SagaError):
            await saga.execute()

        assert compensated == ["bad"]
