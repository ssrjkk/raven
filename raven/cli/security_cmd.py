from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, NoReturn

import click
from rich.console import Console

if TYPE_CHECKING:
    from raven.core.auth.store import AuthStore

console = Console()


@click.group(name="security")
def security_group():
    """Security audit and policy management"""


@security_group.command("audit")
@click.option("--deep", is_flag=True, help="Run deep audit (network, env file, dependencies)")
@click.option("--fix", is_flag=True, help="Auto-fix common issues")
def security_audit(deep: bool, fix: bool):
    """Run comprehensive security audit checks"""
    from raven.cli.doctor import _render_security_audit
    from raven.core.security.security_audit import SecurityAudit

    auditor = SecurityAudit()
    results = auditor.run_all(deep=deep)
    _render_security_audit(results, fix=fix)


def _refuse(reason: str) -> NoReturn:
    console.print(f"[red]refused[/red] {reason}")
    raise SystemExit(1)


def _resolve_password(value: str | None) -> str | None:
    """`--password -` reads the value from stdin so it stays out of the process list and shell history."""
    from raven.core.auth.password import check_password_strength

    if value is None:
        return None
    password = sys.stdin.readline().rstrip("\r\n") if value == "-" else value
    if not password:
        return _refuse("an empty password logs nobody in — authenticate() refuses it")
    try:
        # the same policy /api/auth/register enforces; a bootstrap that skipped it would mint the
        # most privileged account in the system on a credential the documented rules refuse
        check_password_strength(password)
    except ValueError as exc:
        return _refuse(f"{exc} — refusing to write it into an admin account")
    return password


@security_group.command("promote")
@click.argument("username")
@click.option("--password", "password_arg", default=None, help="Password for the account; '-' reads it from stdin")
@click.option("--activate", is_flag=True, help="Switch a deactivated account back on")
def security_promote(username: str, password_arg: str | None, activate: bool) -> None:
    """Give an account the admin role the login path can actually reach."""
    from raven.core.auth.store import AuthStore
    from raven.core.config import settings

    password = _resolve_password(password_arg)

    async def _promote() -> int:
        store = AuthStore(settings.resolved_db_path)
        try:
            return await _promote_into(store, username, password, activate)
        finally:
            await store.close()

    raise SystemExit(asyncio.run(_promote()))


async def _promote_into(store: AuthStore, username: str, password: str | None, activate: bool) -> int:
    from raven.core.auth.models import Role

    admin = Role.ADMIN.value
    user = await store.get_user(username)

    if user is None:
        if password is None:
            return _refuse(f"{username} has no account row and no password to create one — re-run with --password")
        await store.create_user(username, password, role=admin)
        console.print(f"[green]created[/green] admin account {username} (role {admin}, password set)")
        return 0

    if not user.is_active and not activate:
        return _refuse(
            f"{username} is deactivated (is_active={int(user.is_active)}): its logins are refused and every "
            "session it holds is rejected — re-run with --activate"
        )
    if not user.password_hash and password is None:
        return _refuse(
            f"{username} has an empty password_hash, so authenticate() refuses every login and an admin role "
            "would change nothing about that — re-run with --password"
        )

    changes: list[str] = []
    # Counted before the writes: auth_sessions stores the role as it was at login, and both
    # update_role() and update_password() drop the sessions they invalidate as they go, so the
    # number has to be read while the rows are still there.
    revoked = await store.count_user_sessions(user.id)
    if user.role.value != admin:
        await store.update_role(username, admin)
        changes.append(f"role {user.role.value} -> {admin}")
    if password is not None:
        await store.update_password(username, password)
        changes.append("password set")
    if activate and not user.is_active:
        await store.set_active(username, True)
        changes.append("activated")

    if not changes:
        console.print(f"[OK] {username} is already a reachable admin — nothing changed, sessions left alone")
        return 0

    changes.append(f"{revoked} session(s) revoked")
    console.print(f"[green]promoted[/green] {username}: {', '.join(changes)}")
    return 0
