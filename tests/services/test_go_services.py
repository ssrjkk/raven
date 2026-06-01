from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

GO_ROOT = Path(__file__).resolve().parent.parent.parent / "services"
GO_BUILDER = "C:\\Program Files\\Go\\bin\\go.exe"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_go_service(name: str) -> Path:
    svc_dir = GO_ROOT / name
    out = svc_dir / "bin" / f"{name}.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [GO_BUILDER, "build", "-o", str(out), "."],
        cwd=str(svc_dir),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Go build failed for {name}: {result.stderr}")
    return out


def wait_for_health(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{url}/health", timeout=2)
            if r.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.3)
    return False


@pytest.fixture(scope="module")
def auth_binary():
    yield build_go_service("auth")


@pytest.fixture(scope="module")
def monitor_binary():
    yield build_go_service("monitor-engine")


@pytest.fixture(scope="module")
def gateway_binary():
    yield build_go_service("gateway")


class TestAuthService:
    """Integration tests for Go auth service (register → login → validate)."""

    @pytest.fixture(autouse=True)
    def setup(self, auth_binary):
        port = find_free_port()
        db_dir = tempfile.mkdtemp()
        db_path = os.path.join(db_dir, "auth.db")
        self.base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        env.update({
            "SERVICE_PORT": str(port),
            "DB_PATH": db_path,
            "JWT_SECRET": "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
            "NATS_URL": "",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        })

        self.proc = subprocess.Popen(
            [str(auth_binary)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert wait_for_health(self.base_url), "Auth service failed to start"
        yield
        self.proc.kill()
        self.proc.wait()

    def test_health(self):
        r = httpx.get(f"{self.base_url}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["service"] == "auth"

    def test_ready(self):
        r = httpx.get(f"{self.base_url}/ready", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_metrics(self):
        r = httpx.get(f"{self.base_url}/metrics", timeout=5)
        assert r.status_code == 200

    def test_register_and_login(self):
        username = f"testuser_{int(time.time())}"
        password = "testpass123"

        r = httpx.post(
            f"{self.base_url}/api/v1/auth/register",
            json={"username": username, "password": password},
            timeout=5,
        )
        assert r.status_code == 201
        user_id = r.json()["user_id"]
        assert len(user_id) > 0

        r = httpx.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=5,
        )
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["user_id"] == user_id

        r = httpx.post(
            f"{self.base_url}/api/v1/auth/validate",
            json={"token": data["token"]},
            timeout=5,
        )
        assert r.status_code == 200
        vdata = r.json()
        assert vdata["valid"] is True
        assert vdata["user_id"] == user_id

    def test_register_duplicate(self):
        username = f"dup_{int(time.time())}"
        payload = {"username": username, "password": "testpass123"}
        r = httpx.post(f"{self.base_url}/api/v1/auth/register", json=payload, timeout=5)
        assert r.status_code == 201
        r = httpx.post(f"{self.base_url}/api/v1/auth/register", json=payload, timeout=5)
        assert r.status_code == 409

    def test_login_invalid(self):
        r = httpx.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"username": "nonexistent", "password": "badpass"},
            timeout=5,
        )
        assert r.status_code == 401

    def test_validate_invalid_token(self):
        r = httpx.post(
            f"{self.base_url}/api/v1/auth/validate",
            json={"token": "invalid.jwt.token"},
            timeout=5,
        )
        assert r.status_code in (200, 401)
        assert r.json()["valid"] is False

    def test_validation_short_password(self):
        r = httpx.post(
            f"{self.base_url}/api/v1/auth/register",
            json={"username": f"shortpwd_{int(time.time())}", "password": "123"},
            timeout=5,
        )
        assert r.status_code == 400


class TestMonitorEngine:
    """Integration tests for Go monitor-engine service."""

    @pytest.fixture(autouse=True)
    def setup(self, monitor_binary):
        port = find_free_port()
        db_dir = tempfile.mkdtemp()
        db_path = os.path.join(db_dir, "monitor.db")
        self.base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        env.update({
            "SERVICE_PORT": str(port),
            "DB_PATH": db_path,
            "NATS_URL": "",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        })

        self.proc = subprocess.Popen(
            [str(monitor_binary)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert wait_for_health(self.base_url), "Monitor engine failed to start"
        yield
        self.proc.kill()
        self.proc.wait()

    def test_health(self):
        r = httpx.get(f"{self.base_url}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["service"] == "monitor-engine"

    def test_ready(self):
        r = httpx.get(f"{self.base_url}/ready", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_list_empty(self):
        r = httpx.get(f"{self.base_url}/api/v1/monitors", timeout=5)
        assert r.status_code == 200
        assert r.json()["monitors"] == []

    def test_create_monitor(self):
        r = httpx.post(
            f"{self.base_url}/api/v1/monitors",
            json={"name": "Test HTTP", "url": "http://example.com", "interval_seconds": 60, "timeout_seconds": 5},
            timeout=5,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Test HTTP"
        assert data["url"] == "http://example.com"
        assert data["enabled"] is True
        assert len(data["id"]) > 0

        r = httpx.get(f"{self.base_url}/api/v1/monitors", timeout=5)
        assert len(r.json()["monitors"]) == 1

    def test_delete_monitor(self):
        r = httpx.post(
            f"{self.base_url}/api/v1/monitors",
            json={"name": "ToDelete", "url": "http://example.com"},
            timeout=5,
        )
        assert r.status_code == 201
        mon_id = r.json()["id"]

        r = httpx.delete(f"{self.base_url}/api/v1/monitors/{mon_id}", timeout=5)
        assert r.status_code == 204

        r = httpx.get(f"{self.base_url}/api/v1/monitors", timeout=5)
        assert r.json()["monitors"] == []


class TestGatewayService:
    """Integration tests for Go gateway service (health/ready, no backends)."""

    @pytest.fixture(autouse=True)
    def setup(self, gateway_binary):
        port = find_free_port()
        self.base_url = f"http://127.0.0.1:{port}"

        env = os.environ.copy()
        env.update({
            "SERVICE_PORT": str(port),
            "NATS_URL": "",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        })

        self.proc = subprocess.Popen(
            [str(gateway_binary)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert wait_for_health(self.base_url), "Gateway failed to start"
        yield
        self.proc.kill()
        self.proc.wait()

    def test_health(self):
        r = httpx.get(f"{self.base_url}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["service"] == "gateway"

    def test_ready_no_nats(self):
        r = httpx.get(f"{self.base_url}/ready", timeout=5)
        assert r.status_code == 503
        assert r.json()["reason"] == "NATS disconnected"

    def test_metrics(self):
        r = httpx.get(f"{self.base_url}/metrics", timeout=5)
        assert r.status_code == 200

    def test_proxy_to_downstream_returns_502(self):
        r = httpx.post(
            f"{self.base_url}/api/v1/code/execute",
            json={"code": "print(1)", "language": "python"},
            timeout=10,
        )
        assert r.status_code == 502
