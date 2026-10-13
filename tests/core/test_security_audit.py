from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
from typing import Any

import pytest

from raven.core import config as config_module
from raven.core.audit import AUDIT_SIGNING_KEY_ENV, audit_logger
from raven.core.config import SafeSecretStr
from raven.core.security import security_audit as sa


class _Stat:
    def __init__(self, mode: int, size: int = 0) -> None:
        self.st_mode = mode
        self.st_size = size


class _FakePath:
    def __init__(self, *, exists: bool = True, mode: int = 0, is_file: bool = True, size: int = 0) -> None:
        self._exists = exists
        self._stat = _Stat(mode, size)
        self._is_file = is_file

    def exists(self) -> bool:
        return self._exists

    def is_file(self) -> bool:
        return self._is_file

    def stat(self) -> _Stat:
        return self._stat

    def __str__(self) -> str:
        return "<fake-path>"


def _last(auditor: sa.SecurityAudit) -> sa.AuditCheck:
    return auditor._checks[-1]


def _run(method_name: str) -> sa.AuditCheck:
    auditor = sa.SecurityAudit()
    getattr(auditor, method_name)()
    return _last(auditor)


class TestSimpleSettingsBranches:
    def test_dm_policy_open_without_allowlist_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "dm_policy", "open")
        monkeypatch.setattr(config_module.settings, "channel_allow_from", "")
        check = _run("_check_dm_policy")
        assert not check.passed
        assert "CHANNEL_ALLOW_FROM" in check.message

    def test_dm_policy_open_with_allowlist_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "dm_policy", "open")
        monkeypatch.setattr(config_module.settings, "channel_allow_from", "alice")
        assert _run("_check_dm_policy").passed

    def test_dm_policy_unknown_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "dm_policy", "weird")
        assert not _run("_check_dm_policy").passed

    def test_auth_mode_without_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_secret_key", SafeSecretStr(""))
        assert not _run("_check_auth_mode").passed

    def test_secret_key_default_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_secret_key", SafeSecretStr("change-me-in-production"))
        assert not _run("_check_secret_key").passed

    def test_web_bind_non_loopback_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_host", "0.0.0.0")
        assert not _run("_check_web_bind").passed

    def test_tools_exec_without_deny_list_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sa, "_DEFAULT_TOOLS_DENY", ())
        assert not _run("_check_tools_exec").passed

    def test_rate_limiting_disabled_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "rate_limit_max", 0)
        assert not _run("_check_rate_limiting").passed

    def test_channel_allowlist_configured_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "channel_allow_from", "alice")
        assert _run("_check_channel_allowlist").passed

    @pytest.mark.parametrize(
        ("mode", "should_pass"),
        [("none", False), ("non-main", True), ("main", True), ("all", True)],
    )
    def test_sandbox_mode_branches(self, monkeypatch: pytest.MonkeyPatch, mode: str, should_pass: bool) -> None:
        monkeypatch.setattr(config_module.settings, "sandbox_mode", mode)
        assert _run("_check_sandbox_mode").passed is should_pass

    def test_workspace_path_set_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "workspace_path", "/srv/raven/ws")
        assert _run("_check_workspace_path").passed

    def test_tool_overrides_both_set_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "tools_deny", "a")
        monkeypatch.setattr(config_module.settings, "tools_allow", "b")
        assert not _run("_check_tool_overrides").passed

    def test_web_cors_wildcard_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_cors_origins", "*")
        assert not _run("_check_web_cors").passed

    def test_config_validation_failure_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(self: Any) -> bool:
            raise ValueError("bad config")

        monkeypatch.setattr(type(config_module.settings), "validate_settings", _boom)
        check = _run("_check_config_validation")
        assert not check.passed
        assert "bad config" in check.message

    def test_debug_mode_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "log_level", "DEBUG")
        assert not _run("_check_debug_mode").passed

    def test_exec_security_allow_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "exec_security", "allow")
        assert not _run("_check_exec_security").passed

    def test_exec_security_full_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "exec_security", "full")
        assert _run("_check_exec_security").passed

    def test_context_visibility_all_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "context_visibility", "all")
        assert not _run("_check_context_visibility").passed

    def test_session_timeout_too_high_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "llm_timeout", 700)
        assert not _run("_check_session_timeout").passed


class TestEnvDrivenBranches:
    def test_secrets_encryption_with_master_key_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RAVEN_MASTER_KEY", "k")
        assert _run("_check_secrets_encryption").passed

    def test_https_configured_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TLS_KEY_PATH", "/x/key.pem")
        monkeypatch.setenv("TLS_CERT_PATH", "/x/cert.pem")
        check = _run("_check_https_enabled")
        assert check.passed
        assert "TLS configured" in check.message

    def test_signing_key_from_env_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AUDIT_SIGNING_KEY_ENV, "deadbeef")
        check = _run("_check_signing_key")
        assert check.passed
        assert AUDIT_SIGNING_KEY_ENV in check.message

    def test_api_keys_local_provider_base_url_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "default_model", "ollama/llama3")
        monkeypatch.setattr(config_module.settings, "ollama_base_url", "http://localhost:11434")
        check = _run("_check_api_keys")
        assert check.passed
        assert "ollama" in check.message

    def test_api_keys_unknown_provider_without_keys_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "default_model", "mystery/model-x")
        for attr in ("openrouter_api_key", "anthropic_api_key", "openai_api_key", "groq_api_key"):
            monkeypatch.setattr(config_module.settings, attr, SafeSecretStr(""))
        assert not _run("_check_api_keys").passed


class TestFilePermissionBranches:
    def _linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")

    def test_fs_world_readable_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        fake = _FakePath(mode=stat.S_IROTH)
        monkeypatch.setattr(type(config_module.settings), "resolved_db_path", property(lambda self: fake))
        assert not _run("_check_fs_permissions").passed

    def test_fs_missing_db_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakePath(exists=False)
        monkeypatch.setattr(type(config_module.settings), "resolved_db_path", property(lambda self: fake))
        check = _run("_check_fs_permissions")
        assert check.passed
        assert "does not exist" in check.message

    def test_log_world_readable_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        fake = _FakePath(mode=stat.S_IROTH)
        monkeypatch.setattr(type(config_module.settings), "resolved_log_file", property(lambda self: fake))
        assert not _run("_check_log_permissions").passed

    def test_log_restricted_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        fake = _FakePath(mode=0)
        monkeypatch.setattr(type(config_module.settings), "resolved_log_file", property(lambda self: fake))
        check = _run("_check_log_permissions")
        assert check.passed
        assert "permissions OK" in check.message

    def test_secret_file_world_readable_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(mode=stat.S_IROTH))
        assert not _run("_check_secret_file_perms").passed

    def test_secret_file_restricted_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(mode=0))
        check = _run("_check_secret_file_perms")
        assert check.passed
        assert "permissions OK" in check.message

    def test_env_file_world_readable_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(mode=stat.S_IROTH))
        assert not _run("_check_env_file_perms").passed

    def test_env_file_restricted_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._linux(monkeypatch)
        monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(mode=0))
        check = _run("_check_env_file_perms")
        assert check.passed
        assert "permissions OK" in check.message


class TestDependencyImportBranches:
    def test_pii_redaction_no_patterns_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core.security import context_filter as cf

        monkeypatch.setattr(cf.PIIEngine, "_build_patterns", staticmethod(lambda: []))
        assert not _run("_check_pii_redaction").passed

    def test_pii_redaction_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "raven.core.security.context_filter", None)
        check = _run("_check_pii_redaction")
        assert not check.passed
        assert "not available" in check.message

    def test_audit_chain_broken_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audit_logger, "verify_chain", lambda: [{"valid": False}])
        check = _run("_check_audit_chain")
        assert not check.passed
        assert "chain errors" in check.message

    def test_plugin_isolation_global_deny_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core import plugin_sandbox as ps_mod

        monkeypatch.setattr(ps_mod.plugin_sandbox, "_global_deny", {"fs.write"})
        check = _run("_check_plugin_isolation")
        assert check.passed
        assert "fs.write" in check.message

    def test_plugin_isolation_per_plugin_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core import plugin_sandbox as ps_mod

        monkeypatch.setattr(ps_mod.plugin_sandbox, "_global_deny", set())
        monkeypatch.setattr(ps_mod.plugin_sandbox, "to_dict", lambda: {"per_plugin": {"p1": {}}})
        check = _run("_check_plugin_isolation")
        assert check.passed
        assert "Per-plugin" in check.message

    def test_plugin_isolation_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "raven.core.plugin_sandbox", None)
        check = _run("_check_plugin_isolation")
        assert not check.passed
        assert "not available" in check.message


class _FakeDockerClient:
    def __init__(self, *, reachable: bool) -> None:
        self._reachable = reachable
        self.closed = False

    def ping(self) -> None:
        if not self._reachable:
            raise RuntimeError("daemon down")

    def close(self) -> None:
        self.closed = True


class TestDockerSandbox:
    def _module(self, monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
        import types

        fake = types.ModuleType("docker")
        fake.from_env = lambda: client  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "docker", fake)

    def test_docker_available_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._module(monkeypatch, _FakeDockerClient(reachable=True))
        check = _run("_check_docker_sandbox")
        assert check.passed
        assert "available" in check.message

    def test_docker_daemon_unreachable_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._module(monkeypatch, _FakeDockerClient(reachable=False))
        assert not _run("_check_docker_sandbox").passed

    def test_docker_not_installed_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "docker", None)
        check = _run("_check_docker_sandbox")
        assert not check.passed
        assert "not installed" in check.message


class TestNetworkExposure:
    def test_check_is_informational(self) -> None:
        assert _run("_check_network_exposure").passed


class TestAuditCheckShape:
    def test_ok_resets_previous_failure(self) -> None:
        c = sa.AuditCheck("n", "d", "high")
        c.fail("broken", fix_hint="fix it")
        c.ok("all good now")
        assert c.passed
        assert c.message == "all good now"

    def test_fix_hint_accessor(self) -> None:
        c = sa.AuditCheck("n", "d")
        assert c.fix_hint() is None
        c.fail("broken", fix_hint="hint")
        assert c.fix_hint() == "hint"

    def test_to_dict_without_hint(self) -> None:
        c = sa.AuditCheck("n", "d")
        c.ok("fine")
        d = c.to_dict()
        assert d["passed"] is True
        assert "fix_hint" not in d

    def test_to_dict_with_hint(self) -> None:
        c = sa.AuditCheck("n", "d")
        c.fail("broken", fix_hint="do the thing")
        d = c.to_dict()
        assert d["fix_hint"] == "do the thing"


# ─── run_all orchestration ───────────────────────────────────────────


def test_run_all_shallow_returns_base_checks() -> None:
    checks = sa.SecurityAudit().run_all(deep=False)
    names = [c.name for c in checks]
    assert "dm_policy" in names
    assert "context_visibility" in names
    assert "dependency_audit" not in names  # deep-only


def test_run_all_deep_includes_deep_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
    fake = types.ModuleType("docker")
    fake.from_env = lambda: _FakeDockerClient(reachable=True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docker", fake)
    names = [c.name for c in sa.SecurityAudit().run_all(deep=True)]
    assert {"dependency_audit", "docker_sandbox", "token_expiry", "network_exposure"} <= set(names)


# ─── _parse_pip_audit_findings ───────────────────────────────────────


def test_parse_findings_dict_shape() -> None:
    raw = json.dumps(
        {
            "dependencies": [
                {"name": "a", "version": "1", "vulns": [{"id": "X"}]},
                {"name": "b", "version": "2", "vulns": []},
            ]
        }
    )
    assert sa._parse_pip_audit_findings(raw) == ["a==1"]


def test_parse_findings_bare_list() -> None:
    raw = json.dumps([{"name": "c", "version": "3", "vulns": [{"id": "Y"}]}])
    assert sa._parse_pip_audit_findings(raw) == ["c==3"]


def test_parse_findings_invalid_json() -> None:
    assert sa._parse_pip_audit_findings("{{{not json") is None


def test_parse_findings_entries_not_list() -> None:
    assert sa._parse_pip_audit_findings(json.dumps({"foo": "bar"})) is None


# ─── _check_dependencies ─────────────────────────────────────────────


class TestDependencyAudit:
    def _installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(importlib.util, "find_spec", lambda _n: object())

    def test_not_installed_returns_early(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(importlib.util, "find_spec", lambda _n: None)
        check = _run("_check_dependencies")
        assert check.passed
        assert "not installed" in check.message

    def test_timeout_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._installed(monkeypatch)

        def _boom(*_a: Any, **_k: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="pip_audit", timeout=1)

        monkeypatch.setattr(subprocess, "run", _boom)
        check = _run("_check_dependencies")
        assert not check.passed
        assert "did not finish" in check.message

    def test_clean_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._installed(monkeypatch)

        class _R:
            returncode = 0
            stdout = b"{}"
            stderr = b""

        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _R())
        check = _run("_check_dependencies")
        assert check.passed
        assert "no known vulnerabilities" in check.message

    def test_vulnerable_findings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._installed(monkeypatch)
        payload = json.dumps({"dependencies": [{"name": "foo", "version": "1.0", "vulns": [{"id": "CVE"}]}]})

        class _R:
            returncode = 1
            stdout = payload.encode("utf-8")
            stderr = b""

        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _R())
        check = _run("_check_dependencies")
        assert not check.passed
        assert "foo==1.0" in check.message

    def test_unparsable_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._installed(monkeypatch)

        class _R:
            returncode = 1
            stdout = b"not json at all"
            stderr = b"network unreachable"

        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _R())
        check = _run("_check_dependencies")
        assert not check.passed
        assert "could not complete" in check.message


# ─── _check_token_expiry ─────────────────────────────────────────────


def test_token_expiry_counts_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import raven.core.channel_config as cc

    monkeypatch.setattr(cc, "get_channel_config", lambda _name: {"bot_token": "tok"})
    check = _run("_check_token_expiry")
    assert check.passed
    assert "3 token" in check.message


# ─── _check_signing_key file branches ────────────────────────────────


def test_signing_key_file_present_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUDIT_SIGNING_KEY_ENV, raising=False)
    monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(is_file=True, size=64))
    check = _run("_check_signing_key")
    assert check.passed
    assert "Signing key present" in check.message


def test_signing_key_absent_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUDIT_SIGNING_KEY_ENV, raising=False)
    monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(is_file=False, size=0))
    check = _run("_check_signing_key")
    assert not check.passed
    assert "unsigned" in check.message


# ─── platform N/A branches (forced win32) ────────────────────────────


class TestWindowsNaBranches:
    def _win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")

    def test_secret_file_na(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._win(monkeypatch)
        monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(exists=True))
        check = _run("_check_secret_file_perms")
        assert check.passed
        assert "N/A" in check.message

    def test_env_file_na(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._win(monkeypatch)
        monkeypatch.setattr(sa, "Path", lambda _p: _FakePath(exists=True))
        check = _run("_check_env_file_perms")
        assert check.passed
        assert "manually" in check.message

    def test_log_na(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._win(monkeypatch)
        monkeypatch.setattr(
            type(config_module.settings),
            "resolved_log_file",
            property(lambda self: _FakePath(exists=True)),
        )
        check = _run("_check_log_permissions")
        assert check.passed
        assert "N/A" in check.message


# ─── remaining ok / alternate branches ───────────────────────────────


class TestRemainingBranches:
    def test_dm_policy_pairing_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "dm_policy", "pairing")
        check = _run("_check_dm_policy")
        assert check.passed
        assert "pairing" in check.message

    def test_auth_mode_with_key_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_secret_key", SafeSecretStr("s3cret"))
        assert _run("_check_auth_mode").passed

    def test_secret_key_custom_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_secret_key", SafeSecretStr("real-key"))
        assert _run("_check_secret_key").passed

    def test_web_bind_loopback_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_host", "127.0.0.1")
        assert _run("_check_web_bind").passed

    def test_tools_exec_deny_active_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sa, "_DEFAULT_TOOLS_DENY", ("exec", "fs.write"))
        check = _run("_check_tools_exec")
        assert check.passed
        assert "exec" in check.message

    def test_fs_restricted_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        fake = _FakePath(mode=0)
        monkeypatch.setattr(type(config_module.settings), "resolved_db_path", property(lambda self: fake))
        check = _run("_check_fs_permissions")
        assert check.passed
        assert "permissions OK" in check.message

    def test_secrets_no_master_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RAVEN_MASTER_KEY", raising=False)
        check = _run("_check_secrets_encryption")
        assert check.passed
        assert check.fix_hint() is not None

    def test_rate_limiting_enabled_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "rate_limit_max", 60)
        assert _run("_check_rate_limiting").passed

    def test_channel_allowlist_missing_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "channel_allow_from", "")
        check = _run("_check_channel_allowlist")
        assert check.passed
        assert check.fix_hint() is not None

    def test_workspace_missing_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "workspace_path", "")
        check = _run("_check_workspace_path")
        assert check.passed
        assert check.fix_hint() is not None

    def test_pii_redaction_active_ok(self) -> None:
        check = _run("_check_pii_redaction")
        assert check.passed
        assert "patterns" in check.message

    def test_plugin_isolation_none_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from raven.core import plugin_sandbox as ps_mod

        monkeypatch.setattr(ps_mod.plugin_sandbox, "_global_deny", set())
        monkeypatch.setattr(ps_mod.plugin_sandbox, "to_dict", lambda: {"per_plugin": {}})
        check = _run("_check_plugin_isolation")
        assert check.passed
        assert check.fix_hint() is not None

    def test_tool_overrides_unambiguous_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "tools_deny", "")
        assert _run("_check_tool_overrides").passed

    def test_web_cors_restricted_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "web_cors_origins", "http://localhost:5173")
        assert _run("_check_web_cors").passed

    def test_https_missing_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("TLS_KEY_PATH", "TLS_CERT_PATH", "SSL_KEY_FILE", "SSL_CERT_FILE"):
            monkeypatch.delenv(var, raising=False)
        check = _run("_check_https_enabled")
        assert check.passed
        assert check.fix_hint() is not None

    def test_api_key_provider_configured_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "default_model", "openai/gpt-4")
        monkeypatch.setattr(config_module.settings, "openai_api_key", SafeSecretStr("sk-abc"))
        check = _run("_check_api_keys")
        assert check.passed
        assert "openai" in check.message

    def test_api_key_provider_missing_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "default_model", "openai/gpt-4")
        monkeypatch.setattr(config_module.settings, "openai_api_key", SafeSecretStr(""))
        assert not _run("_check_api_keys").passed

    def test_api_keys_local_base_url_missing_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "default_model", "ollama/llama3")
        monkeypatch.setattr(config_module.settings, "ollama_base_url", "")
        assert not _run("_check_api_keys").passed

    def test_api_keys_unknown_with_other_keys_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "default_model", "mystery/model-x")
        monkeypatch.setattr(config_module.settings, "openai_api_key", SafeSecretStr("sk-abc"))
        check = _run("_check_api_keys")
        assert check.passed
        assert "no dedicated key check" in check.message

    def test_config_validation_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(type(config_module.settings), "validate_settings", lambda self: True)
        check = _run("_check_config_validation")
        assert check.passed
        assert "valid" in check.message

    def test_debug_mode_off_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "log_level", "INFO")
        assert _run("_check_debug_mode").passed

    def test_exec_security_deny_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "exec_security", "deny")
        assert _run("_check_exec_security").passed

    def test_context_visibility_restricted_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "context_visibility", "allowlist")
        assert _run("_check_context_visibility").passed

    def test_session_timeout_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config_module.settings, "llm_timeout", 120)
        check = _run("_check_session_timeout")
        assert check.passed
        assert "120" in check.message

    def test_audit_chain_intact_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audit_logger, "verify_chain", lambda: [])
        check = _run("_check_audit_chain")
        assert check.passed
        assert "intact" in check.message
