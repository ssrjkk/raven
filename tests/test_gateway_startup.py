from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_MAIN_PATH = Path(__file__).resolve().parent.parent / "main.py"
_spec = importlib.util.spec_from_file_location("raven_unified_launcher", _MAIN_PATH)
assert _spec is not None and _spec.loader is not None
launcher: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def _fake_flow_daemon(events: list[str], blocking: bool = False) -> type:
    class FakeDaemon:
        def __init__(self, port: int = 18789) -> None:
            self.port = port

        async def start(self) -> None:
            events.append(f"flow-start:{self.port}")
            if not blocking:
                return
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                events.append("flow-cancelled")
                raise

    return FakeDaemon


class TestStartWeb:
    async def test_wires_gateway_to_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import raven.cli.gateway_runner as runner

        sentinel = object()
        calls: list[tuple[object, int]] = []

        def fake_create_gateway() -> object:
            return sentinel

        async def fake_run_gateway(gateway: object, port: int) -> None:
            calls.append((gateway, port))

        monkeypatch.setattr(runner, "create_gateway", fake_create_gateway)
        monkeypatch.setattr(runner, "_run_gateway", fake_run_gateway)

        await launcher._start_web(18888)
        assert calls == [(sentinel, 18888)]

    async def test_import_error_is_soft(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import raven.cli.gateway_runner as runner

        def boom() -> None:
            raise ImportError("optional deps missing")

        monkeypatch.setattr(runner, "create_gateway", boom)
        await launcher._start_web(1)


class TestStartFlow:
    async def test_wires_daemon_to_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import raven.gateway.daemon as daemon_mod

        events: list[str] = []
        monkeypatch.setattr(daemon_mod, "RavenFlowDaemon", _fake_flow_daemon(events))

        await launcher._start_flow(18789)
        assert events == ["flow-start:18789"]

    async def test_import_error_is_soft(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import raven.gateway.daemon as daemon_mod

        class Boom:
            def __init__(self, **kwargs: int) -> None:
                raise ImportError("optional deps missing")

        monkeypatch.setattr(daemon_mod, "RavenFlowDaemon", Boom)
        await launcher._start_flow(1)


class TestUnifiedLauncher:
    async def test_starts_both_components_on_distinct_ports(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import raven.cli.gateway_runner as runner
        import raven.gateway.daemon as daemon_mod

        events: list[str] = []

        async def fake_run_gateway(gateway: object, port: int) -> None:
            events.append(f"web-run:{port}")

        monkeypatch.setattr(runner, "create_gateway", lambda: object())
        monkeypatch.setattr(runner, "_run_gateway", fake_run_gateway)
        monkeypatch.setattr(daemon_mod, "RavenFlowDaemon", _fake_flow_daemon(events, blocking=True))
        monkeypatch.setattr(sys, "argv", ["main.py"])

        await asyncio.wait_for(launcher.main(), timeout=10)

        assert "web-run:18888" in events
        assert "flow-start:18789" in events
        assert "flow-cancelled" in events

    async def test_no_flow_flag_skips_flow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import raven.cli.gateway_runner as runner
        import raven.gateway.daemon as daemon_mod

        events: list[str] = []
        created: list[int] = []

        class TrackingDaemon:
            def __init__(self, port: int = 0) -> None:
                created.append(port)

            async def start(self) -> None:
                await asyncio.sleep(3600)

        async def fake_run_gateway(gateway: object, port: int) -> None:
            events.append(f"web-run:{port}")

        monkeypatch.setattr(runner, "create_gateway", lambda: object())
        monkeypatch.setattr(runner, "_run_gateway", fake_run_gateway)
        monkeypatch.setattr(daemon_mod, "RavenFlowDaemon", TrackingDaemon)
        monkeypatch.setattr(sys, "argv", ["main.py", "--no-flow"])

        await asyncio.wait_for(launcher.main(), timeout=10)

        assert events == ["web-run:18888"]
        assert created == []


@pytest.mark.parametrize("flag,absent,port", [("--no-web", "web-run", 18789), ("--no-flow", "flow-start", 18888)])
class TestSkipFlags:
    async def test_flag_skips_component(
        self,
        monkeypatch: pytest.MonkeyPatch,
        flag: str,
        absent: str,
        port: int,
    ) -> None:
        import raven.cli.gateway_runner as runner
        import raven.gateway.daemon as daemon_mod

        events: list[str] = []

        async def fake_run_gateway(gateway: object, p: int) -> None:
            events.append(f"web-run:{p}")

        monkeypatch.setattr(runner, "create_gateway", lambda: object())
        monkeypatch.setattr(runner, "_run_gateway", fake_run_gateway)
        monkeypatch.setattr(daemon_mod, "RavenFlowDaemon", _fake_flow_daemon(events))
        monkeypatch.setattr(sys, "argv", ["main.py", flag])

        await asyncio.wait_for(launcher.main(), timeout=10)

        assert not any(e.startswith(absent) for e in events)
        expected = "flow-start:18789" if flag == "--no-web" else "web-run:18888"
        assert expected in events
