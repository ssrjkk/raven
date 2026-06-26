import contextlib
import os
import tempfile

import pytest

from services.observability_sdk.idempotency import IdempotencyStore


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    with contextlib.suppress(OSError):
        os.unlink(f.name)


class TestIdempotencyStore:
    def test_set_and_get(self, db_path):
        store = IdempotencyStore(db_path)
        store.set("key-1", 200, '{"ok": true}')
        result = store.get("key-1")
        assert result is not None
        assert result["code"] == 200
        assert result["status"] == "completed"

    def test_get_missing_key(self, db_path):
        store = IdempotencyStore(db_path)
        result = store.get("nonexistent")
        assert result is None

    def test_get_expired_key(self, db_path):
        store = IdempotencyStore(db_path)
        store.set("expired-key", 200, "{}", ttl_hours=0)
        result = store.get("expired-key")
        assert result is None

    def test_overwrite_existing_key(self, db_path):
        store = IdempotencyStore(db_path)
        store.set("key-1", 200, '{"old": true}')
        store.set("key-1", 201, '{"new": true}')
        result = store.get("key-1")
        assert result["code"] == 201

    def test_clean_expired(self, db_path):
        store = IdempotencyStore(db_path)
        store.set("old-key", 200, "{}", ttl_hours=0)
        store.set("fresh-key", 200, "{}", ttl_hours=24)
        store.clean_expired()
        assert store.get("old-key") is None
        assert store.get("fresh-key") is not None
