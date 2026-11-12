"""`raven security promote`, at the exact boundary a fresh install leaves the operator at.

Registration writes `role='user'` and the only route that hands out roles (`/api/auth/users`) needs the
admin role to answer, so nothing in the product can create an admin row. These tests pin both halves of
that: the refusals that stop the command from minting an admin nobody can log in as, and the writes that
make one reachable.

Assertions read a whitespace-flattened copy of the output because rich wraps at the console width, which
is a property of the machine running the test, not of the message.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from raven.cli.security_cmd import security_group
from raven.core.config import settings

PASSWORD = "Sup3rSecret!"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "auth.db"
    monkeypatch.setattr(settings, "db_path", str(path))
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _flat(output: str) -> str:
    return " ".join(output.split())


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


async def _seed(
    db_path: Path,
    username: str,
    *,
    password: str = PASSWORD,
    role: str = "user",
    active: bool = True,
    sessions: int = 0,
) -> list[str]:
    """Write the account the way the product would, and return the bearer tokens it already holds."""

    from raven.core.auth.store import AuthStore

    store = AuthStore(str(db_path))
    try:
        await store.create_user(username, password, role=role)
        if not active:
            await store.set_active(username, False)
        return [await store.create_session(f"user:{username}", role) for _ in range(sessions)]
    finally:
        await store.close()


async def _read_back(db_path: Path, username: str) -> dict[str, Any]:
    from raven.core.auth.store import AuthStore

    store = AuthStore(str(db_path))
    try:
        user = await store.get_user(username)
        return {
            "exists": user is not None,
            "role": user.role.value if user else None,
            "password_hash": user.password_hash if user else "",
            "is_active": user.is_active if user else None,
        }
    finally:
        await store.close()


async def _session_alive(db_path: Path, token: str) -> bool:
    from raven.core.auth.store import AuthStore

    store = AuthStore(str(db_path))
    try:
        return await store.get_session(token) is not None
    finally:
        await store.close()


async def _login_role(db_path: Path, username: str, password: str) -> str | None:
    from raven.core.auth.store import AuthStore

    store = AuthStore(str(db_path))
    try:
        user = await store.authenticate(username, password)
        return user.role.value if user else None
    finally:
        await store.close()


class TestRefusals:
    """Every refusal has to leave the row exactly as it found it, and name the flag that lifts it."""

    def test_an_unknown_account_without_a_password_is_not_created(self, db: Path, runner: CliRunner) -> None:
        result = runner.invoke(security_group, ["promote", "ghost"])
        assert result.exit_code == 1
        assert "no account row" in _flat(result.output) and "--password" in result.output
        assert _run(_read_back(db, "ghost"))["exists"] is False

    def test_a_passwordless_account_is_not_promoted_into_a_decoy_admin(self, db: Path, runner: CliRunner) -> None:
        _run(_seed(db, "svc", password=""))
        before = _run(_read_back(db, "svc"))
        result = runner.invoke(security_group, ["promote", "svc"])
        assert result.exit_code == 1
        assert "empty password_hash" in _flat(result.output)
        assert _run(_read_back(db, "svc")) == before, "refusal must not write"

    def test_a_deactivated_account_is_not_promoted_into_a_refused_admin(self, db: Path, runner: CliRunner) -> None:
        _run(_seed(db, "bob", active=False))
        before = _run(_read_back(db, "bob"))
        result = runner.invoke(security_group, ["promote", "bob"])
        assert result.exit_code == 1
        assert "deactivated" in _flat(result.output) and "--activate" in result.output
        assert _run(_read_back(db, "bob")) == before

    @pytest.mark.parametrize("given", ["", " "])
    def test_an_empty_or_blank_password_is_refused_instead_of_hashed(
        self, db: Path, runner: CliRunner, given: str
    ) -> None:
        result = runner.invoke(security_group, ["promote", "ghost", "--password", given])
        assert result.exit_code == 1
        assert _run(_read_back(db, "ghost"))["exists"] is False

    @pytest.mark.parametrize("weak", ["short1!", "alllower1!", "ALLUPPER1!", "NoDigits!!", "NoSpecialAb1"])
    def test_a_password_the_documented_policy_refuses_refuses_an_admin_here(
        self, db: Path, runner: CliRunner, weak: str
    ) -> None:
        result = runner.invoke(security_group, ["promote", "operator", "--password", weak])
        assert result.exit_code == 1
        assert "Password must" in _flat(result.output)
        assert _run(_read_back(db, "operator"))["exists"] is False


class TestPromotions:
    def test_unknown_account_with_a_password_becomes_a_reachable_admin(self, db: Path, runner: CliRunner) -> None:
        result = runner.invoke(security_group, ["promote", "operator", "--password", PASSWORD])
        assert result.exit_code == 0, result.output
        assert "created admin account operator" in _flat(result.output)
        row = _run(_read_back(db, "operator"))
        assert row["role"] == "admin" and row["password_hash"] and row["is_active"] is True
        assert _run(_login_role(db, "operator", PASSWORD)) == "admin"

    def test_a_password_is_read_from_stdin_when_the_value_is_a_dash(self, db: Path, runner: CliRunner) -> None:
        result = runner.invoke(security_group, ["promote", "operator", "--password", "-"], input="FromStdin1!\n")
        assert result.exit_code == 0, result.output
        assert _run(_login_role(db, "operator", "FromStdin1!")) == "admin"

    def test_an_empty_stdin_password_is_refused(self, db: Path, runner: CliRunner) -> None:
        result = runner.invoke(security_group, ["promote", "operator", "--password", "-"], input="\n")
        assert result.exit_code == 1
        assert _run(_read_back(db, "operator"))["exists"] is False

    def test_promoting_a_user_revokes_the_sessions_that_still_call_it_user(self, db: Path, runner: CliRunner) -> None:
        tokens = _run(_seed(db, "alice", sessions=2))
        assert all(_run(_session_alive(db, token)) for token in tokens)
        result = runner.invoke(security_group, ["promote", "alice"])
        assert result.exit_code == 0, result.output
        said = _flat(result.output)
        assert "role user -> admin" in said and "2 session(s) revoked" in said
        assert not any(_run(_session_alive(db, token)) for token in tokens), "the stored role is what RBAC reads"

    def test_promoting_also_sets_a_password_when_one_is_asked_for(self, db: Path, runner: CliRunner) -> None:
        _run(_seed(db, "svc", password=""))
        result = runner.invoke(security_group, ["promote", "svc", "--password", "NewPass1!"])
        assert result.exit_code == 0, result.output
        said = _flat(result.output)
        assert "password set" in said and "role user -> admin" in said
        assert _run(_login_role(db, "svc", "NewPass1!")) == "admin"
        assert _run(_login_role(db, "svc", PASSWORD)) is None, "the old credential is gone, not added"

    def test_activate_switches_the_account_on_with_the_role(self, db: Path, runner: CliRunner) -> None:
        _run(_seed(db, "bob", active=False))
        result = runner.invoke(security_group, ["promote", "bob", "--activate"])
        assert result.exit_code == 0, result.output
        assert "activated" in _flat(result.output)
        row = _run(_read_back(db, "bob"))
        assert row["role"] == "admin" and row["is_active"] is True

    def test_an_already_reachable_admin_is_left_alongside_its_sessions(self, db: Path, runner: CliRunner) -> None:
        tokens = _run(_seed(db, "root", role="admin", sessions=1))
        result = runner.invoke(security_group, ["promote", "root"])
        assert result.exit_code == 0, result.output
        assert "already a reachable admin" in _flat(result.output)
        assert _run(_session_alive(db, tokens[0])), "a no-op must not log the operator out"

    def test_the_password_the_command_set_is_the_one_the_login_path_accepts(self, db: Path, runner: CliRunner) -> None:
        """The whole point: the table says admin *and* `authenticate()` agrees."""
        runner.invoke(security_group, ["promote", "operator", "--password", PASSWORD])
        assert _run(_login_role(db, "operator", PASSWORD)) == "admin"
        assert _run(_login_role(db, "operator", "WrongPass1!")) is None


class TestConnectionOwnership:
    """The command opens the store, so the command closes it: aiosqlite's worker thread is not a
    daemon, and a leaked connection keeps the interpreter alive after the command printed its line."""

    def _spy_on_close(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        from raven.core.auth.store import AuthStore

        closed: list[int] = []
        original = AuthStore.close

        async def spy(self: Any) -> None:
            closed.append(1)
            await original(self)

        monkeypatch.setattr(AuthStore, "close", spy)
        return closed

    def test_a_promotion_closes_the_store(self, db: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        closed = self._spy_on_close(monkeypatch)
        result = runner.invoke(security_group, ["promote", "operator", "--password", PASSWORD])
        assert result.exit_code == 0, result.output
        assert closed == [1]

    def test_a_refusal_closes_the_store(self, db: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        closed = self._spy_on_close(monkeypatch)
        result = runner.invoke(security_group, ["promote", "ghost"])
        assert result.exit_code == 1
        assert closed == [1]
