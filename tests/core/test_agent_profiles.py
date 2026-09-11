from __future__ import annotations

from raven.core.agents.profiles import PROFILES


def test_coder_denies_shell_and_db() -> None:
    denied = set(PROFILES["coder"].denied_tools)
    assert {"shell", "python", "db_query"}.issubset(denied)


def test_readonly_profiles_deny_shell_and_writes() -> None:
    for name in ("architect", "planner", "researcher"):
        denied = set(PROFILES[name].denied_tools)
        assert {"shell", "python", "db_query"}.issubset(denied), name
        assert {"file_write", "file_edit", "file_delete"}.issubset(denied), name


def test_no_stale_shell_tool_name() -> None:
    bad = {"shell_exec", "http_request", "search_web", "web_fetch", "test_run"}
    for profile in PROFILES.values():
        names = set(profile.allowed_tools) | set(profile.denied_tools)
        assert not names & bad, f"{profile.name} still references stale tool names: {names & bad}"


def test_reviewer_qa_security_intend_shell_and_tests() -> None:
    for name in ("reviewer", "qa", "security"):
        allowed = set(PROFILES[name].allowed_tools)
        assert "shell" in allowed, name
        assert "run_tests" in allowed, name
