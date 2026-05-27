import json
import os
import tempfile

import pytest

from services.observability_sdk.outbox import OutboxStore
from services.observability_sdk.outbox_poller import OutboxPoller


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    try:
        os.unlink(f.name)
    except OSError:
        pass


class TestOutboxStore:
    def test_enqueue_and_fetch(self, db_path):
        store = OutboxStore(db_path=db_path, service_name="test")
        eid = store.enqueue("test.subject", {"hello": "world"}, idempotency_key="key-1")
        assert eid is not None

        pending = store.fetch_pending()
        assert len(pending) == 1
        assert pending[0]["subject"] == "test.subject"
        assert json.loads(pending[0]["payload"]) == {"hello": "world"}
        assert pending[0]["status"] == "pending"

    def test_idempotency_key_dedup(self, db_path):
        store = OutboxStore(db_path=db_path, service_name="test")
        eid1 = store.enqueue("test.subject", {"a": 1}, idempotency_key="dup-key")
        eid2 = store.enqueue("test.subject", {"a": 2}, idempotency_key="dup-key")
        assert eid1 == eid2, "Should return same id for duplicate key"

        pending = store.fetch_pending()
        assert len(pending) == 1

    def test_mark_published(self, db_path):
        store = OutboxStore(db_path=db_path, service_name="test")
        eid = store.enqueue("test.subject", {"x": 1})
        store.mark_published(eid)
        pending = store.fetch_pending()
        assert len(pending) == 0

    def test_mark_failed(self, db_path):
        store = OutboxStore(db_path=db_path, service_name="test")
        eid = store.enqueue("test.subject", {"x": 1})
        store.mark_failed(eid, "connection lost")
        pending = store.fetch_pending()
        assert len(pending) == 0

        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT retry_count, last_error FROM outbox WHERE id=?", (eid,)).fetchone()
        assert row[0] == 1
        assert "connection lost" in row[1]

    def test_clean_expired(self, db_path):
        store = OutboxStore(db_path=db_path, service_name="test")
        store.enqueue("test.old", {"old": True})
        store.clean_expired(max_age_hours=0)
        pending = store.fetch_pending()
        assert len(pending) == 0

    def test_thread_local_conn(self, db_path):
        s1 = OutboxStore(db_path=db_path, service_name="t1")
        s2 = OutboxStore(db_path=db_path, service_name="t2")
        assert s1._conn is s1._conn
        assert s2._conn is s2._conn


class TestOutboxPoller:
    @pytest.mark.asyncio
    async def test_poll_and_publish_no_nats(self, db_path):
        store = OutboxStore(db_path=db_path, service_name="test")
        store.enqueue("test.subject", {"data": 42})

        published = []

        class FakeNats:
            async def publish(self, subject, payload, headers=None):
                published.append((subject, payload))

        poller = OutboxPoller(store, FakeNats(), poll_interval=0.1)
        await poller.poll_once()
        pending = store.fetch_pending()
        assert len(pending) == 0
