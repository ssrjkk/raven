from raven.core.auth.models import Permission, Role
from raven.core.auth.rbac import RBAC


class TestRBAC:
    def setup_method(self):
        self.rbac = RBAC()

    def test_admin_has_all_permissions(self):
        for perm in Permission:
            assert self.rbac.has_permission(Role.ADMIN, perm)

    def test_user_has_chat(self):
        assert self.rbac.has_permission(Role.USER, Permission.CHAT)

    def test_user_does_not_have_admin_secrets(self):
        assert not self.rbac.has_permission(Role.USER, Permission.ADMIN_SECRETS)

    def test_banned_has_no_permissions(self):
        for perm in Permission:
            assert not self.rbac.has_permission(Role.BANNED, perm)

    def test_viewer_has_read_only(self):
        assert self.rbac.has_permission(Role.VIEWER, Permission.CHAT)
        assert self.rbac.has_permission(Role.VIEWER, Permission.MONITOR_READ)
        assert not self.rbac.has_permission(Role.VIEWER, Permission.MONITOR_WRITE)

    def test_has_permission_with_string_args(self):
        assert self.rbac.has_permission("admin", "chat")
        assert not self.rbac.has_permission("admin", "nonexistent")
        assert not self.rbac.has_permission("invalid_role", "chat")

    def test_has_permission_with_invalid_permission_string(self):
        assert not self.rbac.has_permission(Role.USER, "not_a_permission")

    def test_add_role_permission(self):
        self.rbac.add_role_permission(Role.BANNED, Permission.CHAT)
        assert self.rbac.has_permission(Role.BANNED, Permission.CHAT)

    def test_add_role_nonexistent(self):
        self.rbac.add_role_permission(Role.BANNED, Permission.CHAT)
        assert self.rbac.has_permission(Role.BANNED, Permission.CHAT)

    def test_remove_role_permission(self):
        self.rbac.remove_role_permission(Role.ADMIN, Permission.CHAT)
        assert not self.rbac.has_permission(Role.ADMIN, Permission.CHAT)

    def test_remove_role_permission_nonexistent(self):
        self.rbac.remove_role_permission(Role.ADMIN, Permission.CHAT)
        self.rbac.remove_role_permission(Role.ADMIN, Permission.CHAT)

    def test_get_role_permissions(self):
        perms = self.rbac.get_role_permissions(Role.BANNED)
        assert perms == []

    def test_require(self):
        assert self.rbac.require(Role.ADMIN, Permission.CHAT)
        assert not self.rbac.require(Role.BANNED, Permission.CHAT)

    def test_require_any(self):
        assert self.rbac.require_any(Role.USER, [Permission.ADMIN_SECRETS, Permission.CHAT])
        assert not self.rbac.require_any(Role.BANNED, [Permission.CHAT])

    def test_require_all(self):
        assert self.rbac.require_all(Role.ADMIN, [Permission.CHAT, Permission.TASK_RUN])
        assert not self.rbac.require_all(Role.USER, [Permission.CHAT, Permission.ADMIN_SECRETS])
