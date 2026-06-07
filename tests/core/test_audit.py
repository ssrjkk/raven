from __future__ import annotations

import tempfile
from pathlib import Path

from raven.core.audit import AuditEntry, AuditEventType, AuditLogger


def test_audit_log_basic():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    logger.log(AuditEventType.SYSTEM_STARTUP, "system", detail={"version": "0.4.0"})
    logger.stop()

    entries = logger.recent()
    assert len(entries) == 1
    assert entries[0]["event"] == "system.startup"
    assert entries[0]["actor"] == "system"

    Path(log_path).unlink(missing_ok=True)


def test_audit_log_sensitive():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    logger.sensitive("pairing_approve", "user1", "user2", True)
    logger.stop()

    entries = logger.recent()
    assert len(entries) == 1
    assert entries[0]["detail"]["sensitive"] is True
    assert entries[0]["detail"]["outcome"] is True

    Path(log_path).unlink(missing_ok=True)


def test_audit_log_recent_limit():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    for i in range(10):
        logger.log("test.event", f"actor{i}")
    logger.stop()

    entries = logger.recent(limit=3)
    assert len(entries) == 3

    Path(log_path).unlink(missing_ok=True)


def test_audit_log_chain_integrity():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path, signing_key=b"0" * 32)
    logger.start()
    logger.log(AuditEventType.SYSTEM_STARTUP, "system")
    logger.log(AuditEventType.MESSAGE_RECEIVED, "user1")
    logger.log(AuditEventType.MESSAGE_SENT, "system")
    logger.stop()

    errors = logger.verify_chain()
    assert len(errors) >= 1
    assert errors[0].get("valid") is True

    Path(log_path).unlink(missing_ok=True)


def test_audit_log_chain_tamper_detection():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path, signing_key=b"0" * 32)
    logger.start()
    logger.log(AuditEventType.SYSTEM_STARTUP, "system")
    logger.log(AuditEventType.MESSAGE_SENT, "system")
    logger.stop()

    with open(log_path, "r") as f:
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


# ─── New tests ──────────────────────────────────────────────────────


def test_audit_query_by_event():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    logger.log("user.login", "alice")
    logger.log("user.logout", "alice")
    logger.log("user.login", "bob")
    logger.stop()

    results = logger.query(event_type="user.login")
    assert len(results) == 2
    assert all(e.event == "user.login" for e in results)

    Path(log_path).unlink(missing_ok=True)


def test_audit_query_by_actor():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    logger.log("user.login", "alice")
    logger.log("user.login", "bob")
    logger.log("user.logout", "alice")
    logger.stop()

    results = logger.query(actor="alice")
    assert len(results) == 2
    assert all(e.actor == "alice" for e in results)

    Path(log_path).unlink(missing_ok=True)


def test_audit_query_limit():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    for i in range(20):
        logger.log("test.event", "user")
    logger.stop()

    results = logger.query(limit=5)
    assert len(results) == 5

    Path(log_path).unlink(missing_ok=True)


def test_audit_query_since():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    import time

    logger = AuditLogger(log_path)
    logger.start()
    logger.log("before", "user")
    time.sleep(0.01)
    mid = time.time()
    logger.log("after", "user")
    logger.stop()

    results = logger.query(since=mid)
    assert len(results) == 1
    assert results[0].event == "after"

    Path(log_path).unlink(missing_ok=True)


def test_audit_stats():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    logger.log("user.login", "alice")
    logger.log("user.login", "bob")
    logger.log("system.boot", "system")
    logger.stop()

    s = logger.stats()
    assert s["total"] == 3
    assert s["by_event"]["user.login"] == 2
    assert s["by_event"]["system.boot"] == 1
    assert s["by_actor"]["alice"] == 1
    assert s["by_actor"]["bob"] == 1
    assert s["parse_errors"] == 0

    Path(log_path).unlink(missing_ok=True)


def test_audit_stats_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    s = logger.stats()
    assert s["total"] == 0

    Path(log_path).unlink(missing_ok=True)


def test_audit_rotation():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path, max_bytes=100)
    logger.start()
    for i in range(50):
        logger.log("test.event", f"user{i}")
    logger.stop()

    count_entries = len(logger.recent(limit=1000))
    assert count_entries >= 1
    assert logger._rotated_count >= 1

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


def test_audit_is_open():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    assert not logger.is_open
    logger.start()
    assert logger.is_open
    logger.stop()
    assert not logger.is_open

    Path(log_path).unlink(missing_ok=True)


def test_audit_verify_signatures_not_enabled():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.start()
    logger.log("test.event", "user")
    logger.stop()

    result = logger.verify_signatures()
    assert len(result) >= 1
    assert result[0].get("note") == "signing not enabled"

    Path(log_path).unlink(missing_ok=True)


def test_audit_log_without_start():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        log_path = f.name

    logger = AuditLogger(log_path)
    logger.log("test.event", "user")

    entries = logger.recent()
    assert len(entries) == 0

    Path(log_path).unlink(missing_ok=True)
