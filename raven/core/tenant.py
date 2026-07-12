from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from raven.core._json import json
from raven.core.config import settings


class Tenant:
    def __init__(
        self,
        id: str,
        name: str,
        db_path: str | None = None,
        isolation_level: str = "database",
        allowed_channels: list[str] | None = None,
        settings_overrides: dict[str, Any] | None = None,
    ):
        self.id = id
        self.name = name
        self.db_path = db_path
        self.isolation_level = isolation_level
        self.allowed_channels = allowed_channels
        self.settings_overrides = settings_overrides or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "db_path": self.db_path,
            "isolation_level": self.isolation_level,
            "allowed_channels": self.allowed_channels,
            "settings_overrides": self.settings_overrides,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tenant:
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            db_path=data.get("db_path"),
            isolation_level=data.get("isolation_level", "database"),
            allowed_channels=data.get("allowed_channels"),
            settings_overrides=data.get("settings_overrides", {}),
        )


class TenantManager:
    def __init__(self, config_path: Path | None = None):
        self._tenants: dict[str, Tenant] = {}
        self._default_db_path: str | None = None
        if config_path:
            self._load_from_config(config_path)

    def _load_from_config(self, config_path: Path) -> None:
        if not config_path.exists():
            logger.debug("Tenant config not found at {}", config_path)
            return
        try:
            raw = config_path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
            tenants_data = data.get("tenants", [])
            for td in tenants_data:
                tenant = Tenant.from_dict(td)
                self._tenants[tenant.id] = tenant
            self._default_db_path = data.get("default_db_path")
            logger.info("Loaded {} tenants from {}", len(tenants_data), config_path)
        except Exception as e:
            logger.error("Failed to load tenant config: {}", e)

    def register_tenant(self, tenant: Tenant) -> None:
        self._tenants[tenant.id] = tenant
        logger.info("Registered tenant: {} ({})", tenant.id, tenant.name)

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def get_db_for_tenant(self, tenant_id: str) -> str:
        tenant = self._tenants.get(tenant_id)
        if tenant and tenant.db_path:
            return tenant.db_path
        if self._default_db_path:
            return self._default_db_path
        return str(settings.resolved_db_path)

    def list_tenants(self) -> list[Tenant]:
        return list(self._tenants.values())

    @property
    def default_db_path(self) -> str | None:
        return self._default_db_path

    @default_db_path.setter
    def default_db_path(self, path: str) -> None:
        self._default_db_path = path

    def is_channel_allowed(self, tenant_id: str, channel: str) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return True
        if tenant.allowed_channels is None:
            return True
        return channel in tenant.allowed_channels

    def get_settings_overrides(self, tenant_id: str) -> dict[str, Any]:
        tenant = self._tenants.get(tenant_id)
        return tenant.settings_overrides if tenant else {}
