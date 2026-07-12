from __future__ import annotations

import pytest

from raven.core.tenant import Tenant, TenantManager


@pytest.fixture
def tenant():
    return Tenant(
        id="tenant-1",
        name="Test Org",
        db_path="/data/tenant-1.db",
        isolation_level="database",
        allowed_channels=["telegram", "discord"],
        settings_overrides={"model": "gpt-4"},
    )


class TestTenant:
    def test_to_dict(self, tenant):
        d = tenant.to_dict()
        assert d["id"] == "tenant-1"
        assert d["name"] == "Test Org"
        assert d["db_path"] == "/data/tenant-1.db"
        assert d["allowed_channels"] == ["telegram", "discord"]

    def test_from_dict(self):
        t = Tenant.from_dict({"id": "t2", "name": "T2", "db_path": "/x.db", "allowed_channels": None})
        assert t.id == "t2"
        assert t.name == "T2"
        assert t.allowed_channels is None


class TestTenantManager:
    def test_register_and_get(self, tenant):
        tm = TenantManager()
        tm.register_tenant(tenant)
        assert tm.get_tenant("tenant-1") is tenant
        assert tm.get_tenant("nonexistent") is None

    def test_list_tenants(self, tenant):
        tm = TenantManager()
        tm.register_tenant(tenant)
        tenants = tm.list_tenants()
        assert len(tenants) == 1
        assert tenants[0].id == "tenant-1"

    def test_get_db_for_tenant(self, tenant):
        tm = TenantManager()
        tm.register_tenant(tenant)
        assert tm.get_db_for_tenant("tenant-1") == "/data/tenant-1.db"
        path = tm.get_db_for_tenant("unknown")
        assert path.endswith(".db")

    def test_channel_allowlist(self, tenant):
        tm = TenantManager()
        tm.register_tenant(tenant)
        assert tm.is_channel_allowed("tenant-1", "telegram") is True
        assert tm.is_channel_allowed("tenant-1", "slack") is False
        assert tm.is_channel_allowed("unknown", "anything") is True

    def test_get_settings_overrides(self, tenant):
        tm = TenantManager()
        tm.register_tenant(tenant)
        overrides = tm.get_settings_overrides("tenant-1")
        assert overrides["model"] == "gpt-4"
        assert tm.get_settings_overrides("unknown") == {}
