"""`raven service` on Windows must reach a module that exists and stop the gateway for real.

`raven/cli/service.py` spawned `python -m daemon.windows_service` -- a module this tree has never had, so
install, start, stop, status and remove each printed a failed command, `install` still claimed
"installed and started", and the SCM never learned anything. The gates below are the four ways that can
come back: a spawn target that does not resolve, a class string the service host cannot import, a stop
that never reaches the gateway, and a success line printed over a nonzero exit.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import inspect
import re
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest

from raven.cli import gateway_runner
from raven.cli import service as service_module
from raven.cli import windows_service as ws

ROOT = Path(__file__).resolve().parents[2]
pywin32 = pytest.mark.skipif(not ws.HAS_PYWIN32, reason="pywin32 is not installed")


def _run_python_targets(rel_path: str) -> list[str]:
    """Every module literal the CLI spawns with `python -m`."""
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    targets: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_run_python"):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            targets.append(first.value)
        elif isinstance(first, ast.Name):
            value = getattr(service_module, first.id, None)
            if isinstance(value, str):
                targets.append(value)
    return targets


class TestSpawnTargetsResolve:
    def test_every_module_the_service_cli_spawns_is_importable(self) -> None:
        targets = _run_python_targets("raven/cli/service.py")
        assert targets, "the scanner found no `python -m` target, so this gate proves nothing"
        for module in targets:
            assert importlib.util.find_spec(module) is not None, f"`{module}` does not resolve"

    def test_no_half_finished_rename_is_left_behind(self) -> None:
        # the original bug was exactly this shape: a `-m` string naming a module nobody ever wrote
        source = (ROOT / "raven" / "cli" / "service.py").read_text(encoding="utf-8")
        assert "daemon.windows_service" not in source


class TestServiceClassIsImportable:
    def test_the_class_string_names_a_module_and_an_attribute(self) -> None:
        # pywin32 writes it to HKLM\\System\\CurrentControlSet\\Services\\RavenAI\\PythonClass and
        # pythonservice.exe imports it, so `__main__` -- what `python -m <module>` makes of the file
        # -- would register a service the host can never start.
        module_name, _, class_name = ws.SERVICE_CLASS_STRING.rpartition(".")
        assert module_name == ws.__name__
        assert class_name
        assert not module_name.startswith("__main__")

    @pywin32
    def test_the_class_the_host_imports_is_a_service_framework_subclass(self) -> None:
        import win32serviceutil

        module_name, _, class_name = ws.SERVICE_CLASS_STRING.rpartition(".")
        cls = getattr(importlib.import_module(module_name), class_name)
        assert issubclass(cls, win32serviceutil.ServiceFramework)
        assert cls._svc_name_ == ws.SERVICE_NAME
        assert cls._svc_display_name_ == ws.SERVICE_DISPLAY_NAME

    def test_the_bundle_names_the_service_module(self) -> None:
        spec = (ROOT / "scripts" / "raven.spec").read_text(encoding="utf-8")
        assert f'"{ws.__name__}"' in spec


class TestWorkingDirectory:
    def test_the_service_does_not_run_from_system32(self) -> None:
        # pythonservice.exe starts with cwd C:\\Windows\\System32 and settings resolve `data/raven.db`
        # against the working directory, so the gateway would build its database inside Windows.
        root = ws.working_directory()
        assert (root / "pyproject.toml").exists()
        assert "windows" not in str(root).lower()


class TestGatewayStopIsReachable:
    def test_request_gateway_stop_is_false_while_no_gateway_runs(self) -> None:
        gateway_runner._stop_control.clear()
        assert gateway_runner.request_gateway_stop() is False

    def test_the_published_stop_event_reaches_the_running_gateway(self) -> None:
        async def scenario() -> bool:
            stop = asyncio.Event()
            gateway_runner._stop_control["gateway"] = (asyncio.get_running_loop(), stop)
            try:
                assert gateway_runner.request_gateway_stop() is True
                await asyncio.wait_for(stop.wait(), timeout=1)
                return stop.is_set()
            finally:
                gateway_runner._stop_control.clear()

        assert asyncio.run(scenario()) is True

    def test_publish_and_withdraw_move_the_handle(self) -> None:
        async def scenario() -> tuple[bool, bool]:
            stop = asyncio.Event()
            gateway_runner.publish_stop_control(stop)
            try:
                published = gateway_runner.request_gateway_stop()
            finally:
                gateway_runner.withdraw_stop_control()
            return published, gateway_runner.request_gateway_stop()

        assert asyncio.run(scenario()) == (True, False)

    def test_the_runner_publishes_the_handle_it_withdraws_on_exit(self) -> None:
        # `raven service stop` reaches the gateway only through this handle, so a runner that starts
        # without publishing (or exits without withdrawing) leaves the service waiting on a thread
        # nobody can ask to finish.
        calls = {
            node.func.id
            for node in ast.walk(ast.parse(inspect.getsource(gateway_runner._run_gateway)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert {"publish_stop_control", "withdraw_stop_control"} <= calls


@pywin32
class TestServeGateway:
    def _handles(self) -> list[int]:
        import win32event

        return [win32event.CreateEvent(None, 0, 0, None) for _ in range(2)]

    def test_a_stop_request_goes_through_the_gateways_own_stop_event(self) -> None:
        import win32event

        stop_requested, finished = self._handles()
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever, name="test-loop", daemon=True)
        loop_thread.start()
        stop = asyncio.Event()
        waiting = asyncio.run_coroutine_threadsafe(stop.wait(), loop)
        gateway_runner._stop_control["gateway"] = (loop, stop)

        def runner() -> None:
            waiting.result(timeout=5)

        try:
            win32event.SetEvent(stop_requested)
            outcome = ws.serve_gateway(stop_requested, finished, runner=runner, grace_seconds=5)
            assert outcome == "stopped"
            assert stop.is_set(), "the SCM stop must shut the gateway down through its own event"
        finally:
            gateway_runner._stop_control.clear()
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)
            loop.close()

    def test_an_already_exited_gateway_is_reported_not_swallowed(self) -> None:
        stop_requested, finished = self._handles()
        outcome = ws.serve_gateway(stop_requested, finished, runner=lambda: None, grace_seconds=5)
        assert outcome == "the gateway exited on its own"

    def test_a_gateway_that_ignores_the_stop_is_reported_as_a_timeout(self) -> None:
        import win32event

        stop_requested, finished = self._handles()
        win32event.SetEvent(stop_requested)
        stuck = threading.Event()
        outcome = ws.serve_gateway(
            stop_requested, finished, runner=lambda: stuck.wait(timeout=30), grace_seconds=0.2
        )
        assert "did not shut down" in outcome
        stuck.set()


class TestInstallIsHonest:
    @pytest.fixture(autouse=True)
    def _pywin32_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # `_install_windows` refuses without it, and the dependency is Windows-only
        monkeypatch.setattr(
            service_module.importlib.util, "find_spec", lambda name: object() if name == "win32serviceutil" else None
        )

    def test_install_registers_the_service_to_start_at_boot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        service_module._install_windows()
        assert [c[2:] for c in calls] == [
            [service_module.SERVICE_MODULE, "install", "--startup=auto"],
            [service_module.SERVICE_MODULE, "start"],
        ]

    def test_a_failed_install_does_not_print_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 5, "", "Access denied as power user")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as excinfo:
            service_module._install_windows()
        assert excinfo.value.code == 1

    def test_a_failed_start_does_not_claim_the_service_is_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            rc = 0 if cmd[3] == "install" else 1
            return subprocess.CompletedProcess(cmd, rc, "", "" if rc == 0 else "The service did not respond")

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(SystemExit) as excinfo:
            service_module._install_windows()
        assert excinfo.value.code == 1


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows branch is not reached elsewhere")
class TestServiceActions:
    @pytest.mark.parametrize("action", ["start", "stop", "status", "remove"])
    def test_each_action_spawns_the_service_module(self, action: str, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        getattr(service_module, f"service_{action}")()
        assert seen == [[sys.executable, "-m", "raven.cli.windows_service", action]]


@pywin32
class TestServiceControlHandler:
    def _service(self) -> Any:
        svc = object.__new__(ws.RavenService)
        svc.ssh = None  # ReportServiceStatus returns early without an SCM handle
        svc.Initialize()
        return svc

    def test_svcstop_signals_the_wait_that_holds_svcdo_run(self) -> None:
        import win32event

        svc = self._service()
        svc.SvcStop()
        assert win32event.WaitForSingleObject(svc._stop_requested, 0) == win32event.WAIT_OBJECT_0

    def test_the_stop_handle_starts_unsignalled(self) -> None:
        import win32event

        svc = self._service()
        assert win32event.WaitForSingleObject(svc._stop_requested, 0) != win32event.WAIT_OBJECT_0


class TestDocumentedContract:
    """`docs/cli.md` is where an operator learns what `raven service install` does to their machine."""

    def test_the_cli_reference_names_what_the_service_registers(self) -> None:
        docs = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
        assert ws.SERVICE_NAME in docs
        assert ws.SERVICE_DISPLAY_NAME in docs
        assert f"{ws.SHUTDOWN_GRACE_SECONDS:.0f} s" in docs

    def test_the_install_hint_names_an_extra_pyproject_declares(self) -> None:
        # A hint the user copies into a shell must name a real extra: naming the bare distribution
        # would skip the floor pyproject sets, and the docs repeat whichever string the code prints.
        hint = re.search(r'pip install "raven\[([a-z-]+)\]"', inspect.getsource(service_module))
        assert hint, "service.py must tell the operator how to install pywin32"
        declared: dict[str, list[str]] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["optional-dependencies"]
        requirements = declared.get(hint.group(1))
        assert requirements, f"{hint.group(1)} is not an extra pyproject declares"
        assert any("pywin32" in req.lower() for req in requirements)
        assert hint.group(1) in (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")

    @pytest.mark.parametrize("claim", ["/etc/systemd/system/raven.service", "com.raven.ai.plist"])
    def test_every_backend_path_the_docs_name_is_a_path_the_code_writes(self, claim: str) -> None:
        docs = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
        assert claim in docs
        assert claim in inspect.getsource(service_module)

    def test_the_guide_hands_the_platform_details_to_the_cli_reference(self) -> None:
        guide = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
        assert "raven service install" in guide
        assert "cli.md" in guide
