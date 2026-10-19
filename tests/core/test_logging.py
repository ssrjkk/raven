import json
from pathlib import Path
from typing import Any, cast

import pytest
from loguru import logger

from raven.core.logging import (
    _enrich_record,
    _serialize,
    correlation_id,
    get_correlation_id,
    set_correlation_id,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _drop_sinks():
    """Every test here installs real sinks; none of them should outlive the test."""
    yield
    logger.remove()


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
    @staticmethod
    def _records(path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_json_lines_reach_the_file(self, tmp_path):
        """A callable `format` is a template factory, so records used to die in `format_map`."""
        log = tmp_path / "raven.log"
        setup_logging(log_file=log, json_format=True)
        logger.info("marker-{}", 7)
        logger.warning("\u043f\u0440\u0438\u0432\u0435\u0442 \u5185\u5bb9")
        records = self._records(log)
        assert "marker-7" in {record["message"] for record in records}
        assert any("\u043f\u0440\u0438\u0432\u0435\u0442" in record["message"] for record in records)

    def test_error_sink_keeps_warnings_upward(self, tmp_path):
        log = tmp_path / "raven.log"
        setup_logging(log_file=log, json_format=True)
        logger.info("just information")
        logger.error("boom")
        levels = {record["level"] for record in self._records(tmp_path / "raven.err.log")}
        assert levels == {"ERROR"}
        assert "just information" in {record["message"] for record in self._records(log)}

    def test_plain_format_still_writes_a_file(self, tmp_path):
        """JSON_LOG=false changes the shape of file logging, not its existence."""
        log = tmp_path / "raven.log"
        setup_logging(log_file=log, json_format=False)
        logger.info("plain marker")
        text = log.read_text(encoding="utf-8")
        assert "plain marker" in text and "| INFO" in text
        assert not text.startswith("{")

    def test_settings_supply_path_level_and_format(self, tmp_path, monkeypatch):
        from raven.core import config as config_module

        log = tmp_path / "from_settings.log"
        monkeypatch.setattr(config_module.settings, "log_file", str(log))
        monkeypatch.setattr(config_module.settings, "json_log", False)
        monkeypatch.setattr(config_module.settings, "log_level", "WARNING")
        setup_logging()
        logger.info("written to file, kept off the console")
        assert "written to file" in log.read_text(encoding="utf-8")

    def test_undocumented_env_var_no_longer_steers_the_path(self, tmp_path, monkeypatch):
        from raven.core import config as config_module

        monkeypatch.setenv("RAVEN_LOG_FILE", str(tmp_path / "legacy.log"))
        log = tmp_path / "settings.log"
        monkeypatch.setattr(config_module.settings, "log_file", str(log))
        setup_logging()
        logger.info("marker")
        assert log.exists()
        assert not (tmp_path / "legacy.log").exists()
