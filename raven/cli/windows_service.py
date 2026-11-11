"""The Windows service host behind `raven service` on Windows.

`raven/cli/service.py` used to spawn `python -m daemon.windows_service`, a module this tree has never
had, so install, start, stop, status and remove each printed a failed command and changed nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from loguru import logger

import raven

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
    import win32timezone  # noqa: F401  the service host imports it for event-log timestamps

    HAS_PYWIN32 = True
    _PYWIN32_ERROR = ""
except ImportError as exc:
    HAS_PYWIN32 = False
    _PYWIN32_ERROR = str(exc)

SERVICE_NAME = "RavenAI"
SERVICE_DISPLAY_NAME = "Raven AI Gateway"
SERVICE_DESCRIPTION = "Runs the Raven AI gateway: channels, tools, routines and the web API."

# pywin32 stores this string in HKLM\...\Services\RavenAI\PythonClass and pythonservice.exe imports it,
# so it has to name the module rather than `__main__`, which is what `python -m <module>` runs it as.
SERVICE_CLASS_STRING = "raven.cli.windows_service.RavenService"

# The gateway forces its own process exit after 30 s of refusing to shut down.
SHUTDOWN_GRACE_SECONDS = 40.0


def working_directory() -> Path:
    """Where the service belongs on disk: the project root, not the SCM's working directory.

    pythonservice.exe starts with cwd `C:\\Windows\\System32`, and settings resolve `data/raven.db`
    and `.env` against the working directory, so a service that stayed there would build its database
    inside Windows.
    """
    package_root = Path(raven.__file__).resolve().parent
    for candidate in (package_root, *package_root.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    return package_root.parent


def _serve_gateway() -> None:
    """Run the same gateway `raven start` runs, to completion, in this thread."""
    from raven.cli.gateway_runner import _run_gateway, create_gateway
    from raven.core.config import settings
    from raven.core.logging import setup_logging

    setup_logging()
    gateway = create_gateway()
    asyncio.run(_run_gateway(gateway, settings.web_port))


def serve_gateway(
    stop_requested: int,
    finished: int,
    *,
    runner: Callable[[], None] = _serve_gateway,
    grace_seconds: float = SHUTDOWN_GRACE_SECONDS,
) -> str:
    """Run the gateway until either the SCM asks to stop or the gateway itself exits.

    The gateway needs its own thread because the wait below has to answer the SCM in this one, and
    the stop has to be a real shutdown: `request_gateway_stop()` sets the same event the POSIX signal
    handlers set, so channels, engines and the database all close instead of being cut off.
    """
    from raven.cli.gateway_runner import request_gateway_stop

    def guarded() -> None:
        try:
            runner()
        except Exception:
            logger.exception("the gateway thread died")
        finally:
            with contextlib.suppress(Exception):
                win32event.SetEvent(finished)

    thread = threading.Thread(target=guarded, name="raven-gateway", daemon=True)
    thread.start()
    signalled = win32event.WaitForMultipleObjects([stop_requested, finished], False, win32event.INFINITE)
    if signalled != win32event.WAIT_OBJECT_0:
        return "the gateway exited on its own"

    if not request_gateway_stop():
        logger.warning("no gateway stop event is published; the thread may not shut down cleanly")
    thread.join(timeout=grace_seconds)
    if thread.is_alive():
        return f"the gateway did not shut down within {grace_seconds:.0f} s"
    return "stopped"


if HAS_PYWIN32:

    class RavenService(win32serviceutil.ServiceFramework):  # type: ignore[misc]  # pywin32 ships no stubs
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args: list[str]) -> None:
            super().__init__(args)
            self.Initialize()

        def Initialize(self) -> None:  # noqa: N802 -- the service host calls these by name
            self._stop_requested = win32event.CreateEvent(None, 0, 0, None)
            self._finished = win32event.CreateEvent(None, 0, 0, None)

        def SvcDoRun(self) -> None:  # noqa: N802
            self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
            os.chdir(working_directory())
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            outcome = serve_gateway(self._stop_requested, self._finished)
            logger.info("Windows service stopping: {}", outcome)

        def SvcStop(self) -> None:  # noqa: N802
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_requested)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not HAS_PYWIN32:
        logger.error("pywin32 is required for the Windows service host: pip install pywin32 ({})", _PYWIN32_ERROR)
        return 1
    if not args:
        # Started by the service control manager through pythonservice.exe: no command line at all.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(RavenService)
        servicemanager.StartServiceCtrlDispatcher()
        return 0
    win32serviceutil.HandleCommandLine(RavenService, serviceClassString=SERVICE_CLASS_STRING, argv=[sys.argv[0], *args])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
