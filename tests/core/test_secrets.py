import os

from raven.core.secrets import SecretsManager


class TestSecretsManager:
    def setup_method(self):
        os.environ["RAVEN_MASTER_KEY"] = "test-master-key-for-testing-only"
        self.mgr = SecretsManager(data_dir="tmp_test_secrets")

    def test_get_default(self):
        assert self.mgr.get("nonexistent") == ""

    def test_get_custom_default(self):
        assert self.mgr.get("nonexistent", "fallback") == "fallback"

    def test_set_and_get(self):
        self.mgr.set("API_KEY", "sk-test")
        assert self.mgr.get("API_KEY") == "sk-test"

    def test_set_overwrites(self):
        self.mgr.set("KEY", "v1")
        self.mgr.set("KEY", "v2")
        assert self.mgr.get("KEY") == "v2"

    def test_unset(self):
        self.mgr.set("KEY", "value")
        self.mgr.unset("KEY")
        assert self.mgr.get("KEY") == ""

    def test_unset_nonexistent(self):
        self.mgr.unset("nonexistent")

    def test_list_keys(self):
        self.mgr.set("A", "1")
        self.mgr.set("B", "2")
        keys = self.mgr.list_keys()
        assert "A" in keys
        assert "B" in keys

    def test_load_once(self):
        self.mgr.load()
        assert self.mgr._loaded is True
        self.mgr.load()
