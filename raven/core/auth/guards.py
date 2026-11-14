"""Request-scope permission guards for handlers narrower than their route-table entry.

`auth_middleware` applies the coarse rule (which permission a method on a path prefix needs). A handler
that guards one secret, a shutdown, or a multi-gigabyte model swap asks here as well, and the answer
comes from `ROLE_PERMISSIONS` rather than from a list of role names typed at the call site — the shape
that quietly grew a `superadmin` role the `Role` enum has never had, in eight places.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from raven.core.auth.models import Permission
from raven.core.auth.rbac import rbac


def caller_role(request: Request) -> str:
    """The role `auth_middleware` resolved for this request, or "" when nothing resolved one."""
    role = getattr(request.state, "user_role", "")
    return str(role or "")


def require_permission(request: Request, permission: Permission, what: str) -> str:
    """The caller's role when it carries `permission`, else a 403 that names what was refused."""
    role = caller_role(request)
    if not rbac.has_permission(role, permission):
        raise HTTPException(403, f"{what} requires the {permission.value} permission")
    return role
