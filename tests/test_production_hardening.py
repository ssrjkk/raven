from __future__ import annotations

import json

import pytest

from raven.core.channel_guardian import TokenBucket
from raven.core.metrics import MetricsCollector


class TestTokenBucketConfigurable:
    def test_token_bucket_accepts_rate_and_burst(self):
        tb = TokenBucket(rate=5.0, burst=10)
        assert tb._rate == 5.0
        assert tb._burst == 10

    def test_token_bucket_default_burst_is_2x_rate(self):
        tb = TokenBucket(rate=8.0)
        assert tb._burst == 16

    async def test_token_bucket_acquire_returns_true_when_tokens_available(self):
        tb = TokenBucket(rate=100.0, burst=100)
        for _ in range(50):
            assert await tb.acquire() is True

    async def test_token_bucket_exhausts_tokens(self):
        tb = TokenBucket(rate=0.1, burst=2)
        assert await tb.acquire() is True
        assert await tb.acquire() is True
        assert await tb.acquire() is False  # exhausted

    async def test_token_bucket_refills_over_time(self):
        tb = TokenBucket(rate=100.0, burst=2)
        assert await tb.acquire() is True
        assert await tb.acquire() is True
        assert await tb.acquire() is False
        assert await tb.acquire() is False


class TestMetricsCollector:
    def test_inc_and_snapshot(self):
        mc = MetricsCollector()
        mc.inc("messages", {"channel": "test"})
        mc.inc("messages", {"channel": "test"})
        snap = mc.snapshot()
        assert snap["raven_messages{channel=test}_total"] == 2

    def test_observe_and_summary(self):
        mc = MetricsCollector()
        mc.observe("latency", 0.5, {"endpoint": "/api"})
        mc.observe("latency", 1.5, {"endpoint": "/api"})
        snap = mc.snapshot()
        assert snap["raven_latency{endpoint=/api}_count"] == 2
        assert snap["raven_latency{endpoint=/api}_avg"] == 1.0

    def test_error_tracking(self):
        mc = MetricsCollector()
        mc.error("send", {"channel": "discord"})
        mc.error("send", {"channel": "discord"})
        snap = mc.snapshot()
        assert snap["raven_send{channel=discord}_errors_total"] == 2

    def test_prometheus_format(self):
        mc = MetricsCollector()
        mc.inc("test_counter")
        mc.observe("test_latency", 0.3)
        output = mc.prometheus()
        assert "raven_test_counter_total 1" in output
        assert "raven_test_latency_count 1" in output
        assert "raven_test_latency_sum" in output

    def test_clear_resets_all(self):
        mc = MetricsCollector()
        mc.inc("test")
        mc.clear()
        snap = mc.snapshot()
        assert len(snap) == 0

    def test_inc_without_labels(self):
        mc = MetricsCollector()
        mc.inc("raw_count")
        assert mc._counters.get("raw_count") == 1


class TestChannelGuardianRateLimitConfig:
    async def test_guardian_rate_limit_from_settings(self, monkeypatch):
        monkeypatch.setattr("raven.core.config.settings.rate_limit_max", "20")
        monkeypatch.setattr("raven.core.config.settings.rate_limit_window", "10")
        from raven.core.channel_guardian import ChannelGuardian

        g = ChannelGuardian()
        from raven.channels.base import BaseChannel

        class FakeChannel(BaseChannel):
            channel_id = "test_ch"
            async def connect(self): pass
            async def disconnect(self): pass
            async def send(self, session_id, message): pass
            async def on_message(self, handler): pass
            async def start(self): pass
            async def stop(self): pass
            async def health_check(self): return True

        g.register(FakeChannel())
        bucket = g._channel_buckets.get("test_ch")
        assert bucket is not None
        assert bucket._rate == 2.0  # 20/10 = 2

    async def test_guardian_rate_limit_custom_settings_edge(self, monkeypatch):
        monkeypatch.setattr("raven.core.config.settings.rate_limit_max", "0")
        monkeypatch.setattr("raven.core.config.settings.rate_limit_window", "1")
        from raven.core.channel_guardian import ChannelGuardian

        g = ChannelGuardian()
        from raven.channels.base import BaseChannel

        class FakeChannel(BaseChannel):
            channel_id = "edge_ch"
            async def connect(self): pass
            async def disconnect(self): pass
            async def send(self, session_id, message): pass
            async def on_message(self, handler): pass
            async def start(self): pass
            async def stop(self): pass
            async def health_check(self): return True

        g.register(FakeChannel())
        bucket = g._channel_buckets.get("edge_ch")
        assert bucket is not None
        assert bucket._rate == 0.0
