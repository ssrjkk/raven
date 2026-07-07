from __future__ import annotations

from raven.core.shared_memory import SharedMemory


class TestSharedMemory:
    def setup_method(self) -> None:
        self.mem = SharedMemory(max_facts=5)

    def test_store_and_get(self):
        self.mem.store("key1", "value1")
        assert self.mem.get("key1") == "value1"

    def test_get_default(self):
        assert self.mem.get("nonexistent", "default") == "default"

    def test_remove(self):
        self.mem.store("key1", "value1")
        self.mem.remove("key1")
        assert self.mem.get("key1") is None

    def test_clear(self):
        self.mem.store("a", 1)
        self.mem.store("b", 2)
        self.mem.clear()
        assert self.mem.count == 0

    def test_keys(self):
        self.mem.store("a", 1)
        self.mem.store("b", 2)
        assert set(self.mem.keys()) == {"a", "b"}

    def test_all(self):
        self.mem.store("a", 1)
        assert self.mem.all() == {"a": 1}

    def test_search(self):
        self.mem.store("alpha", 10)
        self.mem.store("beta", 20)
        result = self.mem.search(lambda k, v: v > 15)
        assert result == {"beta": 20}

    def test_max_facts_eviction(self):
        for i in range(10):
            self.mem.store(f"key{i}", i)
        assert self.mem.count == 5
        assert self.mem.get("key0") is None
        assert self.mem.get("key9") == 9

    def test_thread_safety(self):
        import threading

        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for i in range(20):
                    self.mem.store(f"t{n}_k{i}", i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
