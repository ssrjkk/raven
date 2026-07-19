from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from raven.core.llm.protocol import LLMResponse
from raven.core.metrics import (
    InstrumentedLLMProvider,
    MetricsCollector,
    MetricsServer,
)


@pytest.fixture(autouse=True)
def _disable_prometheus(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("raven.core.metrics.HAS_PROMETHEUS", False)


@pytest.fixture
def collector() -> MetricsCollector:
    return MetricsCollector()


class TestMetricsCollector:
    def test_inc(self, collector: MetricsCollector):
        collector.inc("test_counter")
        assert collector.snapshot()["raven_test_counter_total"] == 1

    def test_inc_with_labels(self, collector: MetricsCollector):
        collector.inc("test", {"status": "ok"})
        snap = collector.snapshot()
        assert snap.get("raven_test_total") is None
        assert snap["raven_test{status=ok}_total"] == 1

    def test_observe(self, collector: MetricsCollector):
        collector.observe("latency", 1.5)
        snap = collector.snapshot()
        assert snap["raven_latency_count"] == 1
        assert snap["raven_latency_sum"] == 1.5

    def test_observe_with_labels(self, collector: MetricsCollector):
        collector.observe("latency", 2.0, {"method": "GET"})
        snap = collector.snapshot()
        assert snap["raven_latency{method=GET}_sum"] == 2.0

    def test_error(self, collector: MetricsCollector):
        collector.error("db_query")
        snap = collector.snapshot()
        assert snap["raven_db_query_errors_total"] == 1

    def test_prometheus_output(self, collector: MetricsCollector):
        collector.inc("requests")
        collector.inc("requests")
        out = collector.prometheus()
        assert "raven_requests_total 2" in out

    def test_clear(self, collector: MetricsCollector):
        collector.inc("x")
        collector.clear()
        assert collector.snapshot() == {}

    def test_max_latency_samples(self, collector: MetricsCollector):
        for i in range(1010):
            collector.observe("x", float(i))
        snap = collector.snapshot()
        assert snap["raven_x_count"] == 1000


class TestMetricsServer:
    async def test_start_stop(self):
        ms = MetricsServer(port=19090)
        await ms.start()
        assert ms._started is True
        await ms.stop()
        assert ms._started is False

    async def test_double_start_idempotent(self):
        ms = MetricsServer(port=19091)
        await ms.start()
        await ms.start()
        assert ms._started is True
        await ms.stop()

    async def test_start_stop_no_prometheus(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("raven.core.metrics.HAS_PROMETHEUS", False)
        ms = MetricsServer(port=19092)
        await ms.start()
        assert ms._started is True
        await ms.stop()


class TestInstrumentedLLMProvider:
    @pytest.mark.asyncio
    async def test_complete_records_metrics(self):
        mock = AsyncMock()
        mock.complete.return_value = LLMResponse(content="ok")
        wrapped = InstrumentedLLMProvider(mock, "test_provider")
        result = await wrapped.complete([{"role": "user", "content": "hi"}], "test-model")
        assert result.content == "ok"
        mock.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_error_records_failure(self):
        mock = AsyncMock()
        mock.complete.side_effect = RuntimeError("fail")
        wrapped = InstrumentedLLMProvider(mock, "test_provider")
        with pytest.raises(RuntimeError):
            await wrapped.complete([], "test-model")

    @pytest.mark.asyncio
    async def test_stream_records_metrics(self):
        async def _stream(*args, **kwargs):
            yield "hello "
            yield "world"

        mock = AsyncMock()
        mock.complete_stream = _stream
        wrapped = InstrumentedLLMProvider(mock, "test_provider")
        tokens = [t async for t in wrapped.complete_stream([], "test-model")]
        assert "".join(tokens) == "hello world"

    @pytest.mark.asyncio
    async def test_cleanup_delegates(self):
        mock = AsyncMock()
        wrapped = InstrumentedLLMProvider(mock, "p")
        await wrapped.cleanup()
        mock.cleanup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_captures_labels(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("raven.core.metrics.HAS_PROMETHEUS", True)
        captured: list[tuple[str, str, dict[str, str] | None]] = []
        monkeypatch.setattr(
            "raven.core.metrics._prom_inc",
            lambda name, labels=None: captured.append(("inc", name, labels)),
        )
        mock = AsyncMock()
        mock.complete.return_value = LLMResponse(content="ok")
        wrapped = InstrumentedLLMProvider(mock, "openai")
        await wrapped.complete([], "gpt-4")
        assert any(c[0] == "inc" and c[1] == "llm_complete" for c in captured)
