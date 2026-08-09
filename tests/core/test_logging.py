import json
from typing import Any, cast

from raven.core.logging import (
    _enrich_record,
    _serialize,
    correlation_id,
    get_correlation_id,
    set_correlation_id,
    setup_logging,
)


class TestCorrelationId:
    def test_get_default(self):
        assert get_correlation_id() == ""

    def test_set_generates(self):
        cid = set_correlation_id()
        assert len(cid) == 32
        assert get_correlation_id() == cid

    def test_set_explicit(self):
        cid = set_correlation_id("my-custom-id")
        assert cid == "my-custom-id"
        assert get_correlation_id() == "my-custom-id"

    def test_set_replaces(self):
        set_correlation_id("first")
        set_correlation_id("second")
        assert get_correlation_id() == "second"


class FakeRecord:
    """Simulates a loguru record dict for _serialize testing."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, key):
        return getattr(self, key, "")

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def get(self, key, default=None):
        return getattr(self, key, default) if hasattr(self, key) else default


class TestSerialize:
    def test_basic(self):
        record = FakeRecord(
            time=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0),
            level=__import__("loguru").logger.level("INFO"),
            name="test_module",
            function="test_func",
            line=42,
            message="hello world",
            extra={"correlation_id": ""},
        )
        result = json.loads(_serialize(record))
        assert result["level"] == "INFO"
        assert result["module"] == "test_module"
        assert result["message"] == "hello world"

    def test_with_exception(self):
        record = FakeRecord(
            time=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0),
            level=__import__("loguru").logger.level("ERROR"),
            name="mod",
            function="fn",
            line=1,
            message="error",
            extra={"correlation_id": ""},
            exception="ValueError: test",
        )
        result = json.loads(_serialize(record))
        assert "exception" in result

    def test_with_extra_fields(self):
        record = FakeRecord(
            time=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0),
            level=__import__("loguru").logger.level("INFO"),
            name="mod",
            function="fn",
            line=1,
            message="test",
            extra={"correlation_id": "", "request_id": "req-123", "user_id": "u1"},
        )
        result = json.loads(_serialize(record))
        assert result["extra"]["request_id"] == "req-123"


class TestEnrichRecord:
    def test_correlation_id_attached(self):
        set_correlation_id("cid-123")
        record = FakeRecord(args=(), extra={})
        assert _enrich_record(cast(Any, record)) is True
        assert record["extra"]["correlation_id"] == "cid-123"

    def test_correlation_id_default_empty(self):
        token = correlation_id.set("")
        try:
            record = FakeRecord(args=(), extra={})
            _enrich_record(cast(Any, record))
            assert record["extra"]["correlation_id"] == ""
        finally:
            correlation_id.reset(token)


class TestSetupLogging:
    def test_console_only(self, tmp_path):
        setup_logging(level="DEBUG", json_format=False)
