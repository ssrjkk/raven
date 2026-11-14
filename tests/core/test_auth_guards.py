"""Unit tests for the one permission guard the narrow handlers now share.

`auth_middleware` decides which permission a *route* needs; these tests cover the check a *handler*
adds on top of it, which is where eight copies of `role in ("admin", "superadmin")` used to live.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from raven.core.auth.guards import caller_role, require_permission
from raven.core.auth.models import Permission


def _request(role: object) -> Any:
    state = SimpleNamespace()
    if role is not None:
        state.user_role = cast(Any, role)
    return cast(Any, SimpleNamespace(state=state))


class TestCallerRole:
    def test_answers_the_role_the_middleware_resolved(self) -> None:
        assert caller_role(_request("viewer")) == "viewer"

    def test_answers_empty_when_nothing_resolved_one(self) -> None:
        assert caller_role(_request(None)) == ""

    def test_stringifies_rather_than_trusts_the_attribute_type(self) -> None:
        """A caller cannot set `user_role` to a non-string, but a stray one must not become a grant."""
        assert isinstance(caller_role(_request(Permission.CHAT)), str)

    def test_a_non_string_is_denied_not_resolved(self) -> None:
        with pytest.raises(HTTPException):
            require_permission(_request(Permission.ADMIN_WRITE), Permission.ADMIN_WRITE, "Config update")


class TestRequirePermission:
    def test_returns_the_role_when_the_table_grants_it(self) -> None:
        assert require_permission(_request("admin"), Permission.ADMIN_SECRETS, "Secret access") == "admin"

    def test_denies_a_role_the_table_excludes(self) -> None:
        for role in ("user", "viewer", "banned"):
            with pytest.raises(HTTPException) as ei:
                require_permission(_request(role), Permission.ADMIN_SECRETS, "Secret access")
            assert ei.value.status_code == 403, role

    def test_denies_a_role_that_does_not_exist(self) -> None:
        """The shape this guard replaced: `superadmin` was admin at those handlers and nowhere else."""
        with pytest.raises(HTTPException) as ei:
            require_permission(_request("superadmin"), Permission.ADMIN_SECRETS, "Secret access")
        assert ei.value.status_code == 403

    def test_denies_an_anonymous_caller(self) -> None:
        with pytest.raises(HTTPException):
            require_permission(_request(None), Permission.ADMIN_WRITE, "Config update")

    def test_the_refusal_names_the_right_it_refused(self) -> None:
        with pytest.raises(HTTPException) as ei:
            require_permission(_request("viewer"), Permission.SYSTEM_SHUTDOWN, "Shutdown")
        assert ei.value.detail == f"Shutdown requires the {Permission.SYSTEM_SHUTDOWN.value} permission"

    def test_every_permission_the_handlers_use_is_reachable_for_admin(self) -> None:
        for permission in (Permission.ADMIN_WRITE, Permission.ADMIN_SECRETS, Permission.SYSTEM_SHUTDOWN):
            assert require_permission(_request("admin"), permission, "x") == "admin"
