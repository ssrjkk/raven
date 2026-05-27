from __future__ import annotations

from pydantic import ValidationError
import pytest

from raven.core.admin_api import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthUpdateRoleRequest,
    ConfigUpdateRequest,
    MonitorCreateRequest,
    MonitorUpdateRequest,
    SecretRequest,
    SSEPushRequest,
)


class TestMonitorCreateRequest:
    def test_valid_monitor(self):
        req = MonitorCreateRequest(
            name="My Monitor",
            type="http",
            target="https://example.com/health",
            interval_seconds=60,
        )
        assert req.name == "My Monitor"
        assert req.target == "https://example.com/health"

    def test_ssrf_blocked_localhost(self):
        with pytest.raises(ValidationError, match="SSRF protection"):
            MonitorCreateRequest(
                name="Bad",
                type="http",
                target="http://localhost:6379",
            )

    def test_ssrf_blocked_127_0_0_1(self):
        with pytest.raises(ValidationError, match="SSRF protection"):
            MonitorCreateRequest(
                name="Bad",
                type="http",
                target="http://127.0.0.1:8080",
            )

    def test_ssrf_blocked_169_254_169_254(self):
        with pytest.raises(ValidationError, match="SSRF protection"):
            MonitorCreateRequest(
                name="AWS metadata",
                type="http",
                target="http://169.254.169.254/latest/meta-data/",
            )

    def test_ssrf_blocked_metadata_google(self):
        with pytest.raises(ValidationError, match="SSRF protection"):
            MonitorCreateRequest(
                name="GCP metadata",
                type="http",
                target="http://metadata.google.internal",
            )

    def test_ssrf_allows_external(self):
        req = MonitorCreateRequest(
            name="External",
            type="http",
            target="https://api.github.com/health",
        )
        assert req.target == "https://api.github.com/health"

    def test_ssrf_allows_non_http_target(self):
        req = MonitorCreateRequest(
            name="File check",
            type="file",
            target="/var/log/app.log",
        )
        assert req.target == "/var/log/app.log"

    def test_ssrf_allows_process_target(self):
        req = MonitorCreateRequest(
            name="Process",
            type="process",
            target="nginx",
        )
        assert req.target == "nginx"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            MonitorCreateRequest(name="", type="http", target="https://example.com")

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            MonitorCreateRequest(name="Test", type="invalid", target="https://example.com")  # type: ignore[arg-type]

    def test_interval_too_low(self):
        with pytest.raises(ValidationError):
            MonitorCreateRequest(
                name="Test", type="http", target="https://example.com", interval_seconds=1,
            )

    def test_interval_too_high(self):
        with pytest.raises(ValidationError):
            MonitorCreateRequest(
                name="Test", type="http", target="https://example.com", interval_seconds=999999,
            )

    def test_invalid_name_characters(self):
        with pytest.raises(ValidationError):
            MonitorCreateRequest(
                name="<script>alert(1)</script>", type="http", target="https://example.com",
            )


class TestMonitorUpdateRequest:
    def test_partial_update(self):
        req = MonitorUpdateRequest(name="New Name")
        assert req.name == "New Name"
        assert req.target is None

    def test_update_ssrf_blocked(self):
        with pytest.raises(ValidationError, match="SSRF protection"):
            MonitorUpdateRequest(target="http://localhost:8080")

    def test_update_allows_external(self):
        req = MonitorUpdateRequest(target="https://api.example.com")
        assert req.target == "https://api.example.com"

    def test_empty_update(self):
        req = MonitorUpdateRequest()
        assert req.name is None
        assert req.target is None


class TestConfigUpdateRequest:
    def test_valid_config(self):
        req = ConfigUpdateRequest(key="DEFAULT_MODEL", value="gpt-4o")
        assert req.key == "DEFAULT_MODEL"
        assert req.value == "gpt-4o"

    def test_empty_key_rejected(self):
        with pytest.raises(ValidationError):
            ConfigUpdateRequest(key="", value="test")

    def test_invalid_key_format(self):
        with pytest.raises(ValidationError):
            ConfigUpdateRequest(key="invalid key!", value="test")

    def test_empty_value_rejected(self):
        with pytest.raises(ValidationError):
            ConfigUpdateRequest(key="TEST_KEY", value="")


class TestSecretRequest:
    def test_valid_secret(self):
        req = SecretRequest(value="sk-or-v1-abc123")
        assert req.value == "sk-or-v1-abc123"

    def test_empty_value_rejected(self):
        with pytest.raises(ValidationError):
            SecretRequest(value="")


class TestAuthLoginRequest:
    def test_valid(self):
        req = AuthLoginRequest(username="admin", password="secret")
        assert req.username == "admin"

    def test_empty_username_rejected(self):
        with pytest.raises(ValidationError):
            AuthLoginRequest(username="", password="secret")

    def test_empty_password_rejected(self):
        with pytest.raises(ValidationError):
            AuthLoginRequest(username="admin", password="")


class TestAuthRegisterRequest:
    def test_valid(self):
        req = AuthRegisterRequest(username="new_user", password="password123")
        assert req.username == "new_user"

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            AuthRegisterRequest(username="user", password="12345")

    def test_invalid_username_chars(self):
        with pytest.raises(ValidationError):
            AuthRegisterRequest(username="user name!", password="password123")

    def test_with_display_name(self):
        req = AuthRegisterRequest(username="user", password="password123", display_name="Full Name")
        assert req.display_name == "Full Name"


class TestAuthUpdateRoleRequest:
    def test_valid_roles(self):
        for role in ("admin", "user", "viewer", "banned"):
            req = AuthUpdateRoleRequest(role=role)
            assert req.role == role

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError):
            AuthUpdateRoleRequest(role="superadmin")  # type: ignore[arg-type]


class TestSSEPushRequest:
    def test_defaults(self):
        req = SSEPushRequest()
        assert req.event == "message"
        assert req.data == {}
        assert req.session is None

    def test_custom_event(self):
        req = SSEPushRequest(event="task_update", data={"id": "123"})
        assert req.event == "task_update"
        assert req.data == {"id": "123"}
