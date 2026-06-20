from __future__ import annotations

from raven.core.auth.models import ROLE_PERMISSIONS, Permission, Role


class RBAC:
    def __init__(self):
        self._extra_permissions: dict[str, set[Permission]] = {}
        self._role_permissions = {r: set(p) for r, p in ROLE_PERMISSIONS.items()}

    def has_permission(self, role: Role | str, permission: Permission | str) -> bool:
        if isinstance(role, str):
            try:
                role = Role(role)
            except ValueError:
                return False
        if isinstance(permission, str):
            try:
                permission = Permission(permission)
            except ValueError:
                return False
        return permission in self._role_permissions.get(role, set())

    def add_role_permission(self, role: Role, permission: Permission):
        if role not in self._role_permissions:
            self._role_permissions[role] = set()
        self._role_permissions[role].add(permission)

    def remove_role_permission(self, role: Role, permission: Permission):
        if role in self._role_permissions:
            self._role_permissions[role].discard(permission)

    def get_role_permissions(self, role: Role) -> list[Permission]:
        return sorted(self._role_permissions.get(role, set()), key=lambda p: p.value)

    def require(self, role: Role | str, permission: Permission | str) -> bool:
        return self.has_permission(role, permission)

    def require_any(self, role: Role | str, permissions: list[Permission | str]) -> bool:
        return any(self.has_permission(role, p) for p in permissions)

    def require_all(self, role: Role | str, permissions: list[Permission | str]) -> bool:
        return all(self.has_permission(role, p) for p in permissions)


rbac = RBAC()
