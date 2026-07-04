from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from raven.core.audit import AUDIT_SIGNING_KEY_ENV, AuditEntry, AuditEventType, AuditLogger


@pytest.mark.asyncio
async def test_audit_log_basic():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log(AuditEventType.SYSTEM_STARTUP, "system", detail={"version": "0.4.0"})
    await logger.stop()

    entries = logger.recent()
    assert len(entries) == 1
    assert entries[0]["event"] == "system.startup"
    assert entries[0]["actor"] == "system"

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_log_sensitive():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.sensitive("pairing_approve", "user1", "user2", True)
    await logger.stop()

    entries = logger.recent()
    assert len(entries) == 1
    assert entries[0]["detail"]["sensitive"] is True
    assert entries[0]["detail"]["outcome"] is True

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_log_recent_limit():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    for i in range(10):
        await logger.log("test.event", f"actor{i}")
    await logger.stop()

    entries = logger.recent(limit=3)
    assert len(entries) == 3

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_log_chain_integrity():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path, signing_key=b"0" * 32)
    logger.start()
    await logger.log(AuditEventType.SYSTEM_STARTUP, "system")
    await logger.log(AuditEventType.MESSAGE_RECEIVED, "user1")
    await logger.log(AuditEventType.MESSAGE_SENT, "system")
    await logger.stop()

    errors = logger.verify_chain()
    assert len(errors) >= 1
    assert errors[0].get("valid") is True

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_log_chain_tamper_detection():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path, signing_key=b"0" * 32)
    logger.start()
    await logger.log(AuditEventType.SYSTEM_STARTUP, "system")
    await logger.log(AuditEventType.MESSAGE_SENT, "system")
    await logger.stop()

    with open(log_path) as f:
        lines = f.readlines()
    modified = lines[0].replace("system.startup", "tampered")
    with open(log_path, "w") as f:
        f.write(modified)
        f.writelines(lines[1:])

    errors = logger.verify_chain()
    assert len(errors) > 0
    assert any(e.get("error") in ("hash_mismatch", "chain_break") for e in errors)

    Path(log_path).unlink(missing_ok=True)


def test_audit_event_type_values():
    assert AuditEventType.TOOL_EXEC.value == "tool.exec"
    assert AuditEventType.POLICY_EVAL.value == "policy.eval"
    assert AuditEventType.PII_REDACTED.value == "pii.redacted"


@pytest.mark.asyncio
async def test_audit_query_by_event():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log("user.login", "alice")
    await logger.log("user.logout", "alice")
    await logger.log("user.login", "bob")
    await logger.stop()

    results = logger.query(event_type="user.login")
    assert len(results) == 2
    assert all(e.event == "user.login" for e in results)

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_query_by_actor():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log("user.login", "alice")
    await logger.log("user.login", "bob")
    await logger.log("user.logout", "alice")
    await logger.stop()

    results = logger.query(actor="alice")
    assert len(results) == 2
    assert all(e.actor == "alice" for e in results)

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_query_limit():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    for _i in range(20):
        await logger.log("test.event", "user")
    await logger.stop()

    results = logger.query(limit=5)
    assert len(results) == 5

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_query_since():
    import time

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log("before", "user")
    time.sleep(0.01)
    mid = time.time()
    await logger.log("after", "user")
    await logger.stop()

    results = logger.query(since=mid)
    assert len(results) == 1
    assert results[0].event == "after"

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_stats():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log("user.login", "alice")
    await logger.log("user.login", "bob")
    await logger.log("system.boot", "system")
    await logger.stop()

    s = logger.stats()
    assert s["total"] == 3
    assert s["by_event"]["user.login"] == 2
    assert s["by_event"]["system.boot"] == 1
    assert s["by_actor"]["alice"] == 1
    assert s["by_actor"]["bob"] == 1
    assert s["parse_errors"] == 0

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_stats_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    s = logger.stats()
    assert s["total"] == 0

    Path(log_path).unlink(missing_ok=True)


def test_audit_entry_from_dict():
    d = {
        "timestamp": 1000.0,
        "event_id": "abc123",
        "event": "test.event",
        "actor": "user",
        "target": "system",
        "detail": {"key": "val"},
        "channel": "web",
        "prev_hash": "000",
        "hash": "111",
        "signature": "222",
    }
    entry = AuditEntry.from_dict(d)
    assert entry.event == "test.event"
    assert entry.actor == "user"
    assert entry.detail["key"] == "val"
    assert entry.hash == "111"


def test_audit_entry_to_dict():
    entry = AuditEntry(
        timestamp=1000.0,
        event_id="abc",
        event="test.event",
        actor="user",
        target="system",
        detail=None,
        channel="",
        prev_hash="000",
        hash="111",
        signature="222",
    )
    d = entry.to_dict()
    assert d["event"] == "test.event"
    assert d["hash"] == "111"
    assert d["signature"] == "222"


def test_audit_entry_repr():
    entry = AuditEntry(timestamp=0, event_id="", event="test.event", actor="user")
    r = repr(entry)
    assert "test.event" in r
    assert "user" in r


def test_audit_entry_timestamp_dt():
    entry = AuditEntry(timestamp=1000000, event_id="", event="test", actor="user")
    dt = entry.timestamp_dt
    assert dt.year >= 1970


def test_audit_path_property():
    logger = AuditLogger("data/test_audit.log")
    assert "test_audit.log" in str(logger.path)


@pytest.mark.asyncio
async def test_audit_is_open():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    assert not logger.is_open
    logger.start()
    assert logger.is_open
    await logger.stop()
    assert not logger.is_open

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_verify_signatures_enabled_by_default():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log("test.event", "user")
    await logger.stop()

    result = logger.verify_signatures()
    assert len(result) >= 1
    assert result[0].get("signatures_verified") is True

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_log_without_start():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    await logger.log("test.event", "user")

    entries = logger.recent()
    assert len(entries) == 0

    Path(log_path).unlink(missing_ok=True)


def test_audit_signing_key_env_var():
    key_hex = "a" * 64
    os.environ[AUDIT_SIGNING_KEY_ENV] = key_hex
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            log_path = f.name

        logger = AuditLogger(log_path)
        assert logger.is_signed
        assert logger.signing_key == bytes.fromhex(key_hex)

        Path(log_path).unlink(missing_ok=True)
    finally:
        os.environ.pop(AUDIT_SIGNING_KEY_ENV, None)


def test_audit_auto_generated_key():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    assert logger.is_signed
    assert logger.signing_key is not None

    Path(log_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_audit_stats_signed_field():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    await logger.log("test.event", "user")
    await logger.stop()

    s = logger.stats()
    assert "signed" in s

    Path(log_path).unlink(missing_ok=True)
