from __future__ import annotations

"""
Windows Service — runs `raven start` as a native Windows service.

Install:
    python -m daemon.windows_service install

Start:
    python -m daemon.windows_service start

Stop:
    python -m daemon.windows_service stop

Remove:
    python -m daemon.windows_service remove
"""

import asyncio
import os
import sys
import threading
from pathlib import Path


SERVICE_NAME = "RavenAI"
SERVICE_DISPLAY_NAME = "Raven AI Service"
SERVICE_DESCRIPTION = "24/7 Personal AI Assistant — Telegram-first, multi-channel gateway"


def _ensure_pywin32():
    try:
        import win32serviceutil  # noqa: F401
    except ImportError:
        print("pywin32 is required for Windows Service support.")
        print("Install: pip install pywin32")
        sys.exit(1)


def _get_script_path() -> str:
    return str(Path(__file__).resolve().parent.parent / "daemon" / "windows_service_runner.py")


class RavenWindowsService:
    """Windows Service wrapper using pywin32."""

    @staticmethod
    def install():
        _ensure_pywin32()
        import win32serviceutil
        import servicemanager
        script = _get_script_path()
        os.system(f'{sys.executable} "{script}" install')
        print(f"Service '{SERVICE_NAME}' installed.")

    @staticmethod
    def start():
        _ensure_pywin32()
        import win32serviceutil
        os.system(f"net start {SERVICE_NAME}")
        print(f"Service '{SERVICE_NAME}' start requested.")

    @staticmethod
    def stop():
        _ensure_pywin32()
        import win32serviceutil
        os.system(f"net stop {SERVICE_NAME}")
        print(f"Service '{SERVICE_NAME}' stop requested.")

    @staticmethod
    def remove():
        _ensure_pywin32()
        import win32serviceutil
        import servicemanager
        script = _get_script_path()
        os.system(f'{sys.executable} "{script}" remove')
        print(f"Service '{SERVICE_NAME}' removed.")

    @staticmethod
    def status():
        _ensure_pywin32()
        import win32serviceutil
        try:
            status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
            state_map = {
                1: "Stopped",
                2: "Starting",
                3: "Stopping",
                4: "Running",
                5: "Continuing",
                6: "Pausing",
                7: "Paused",
            }
            print(f"Service '{SERVICE_NAME}': {state_map.get(status[1], 'Unknown')}")
        except Exception as e:
            print(f"Service '{SERVICE_NAME}': Not installed or not running ({e})")

    @staticmethod
    def run():
        """Entry point when service is started by SCM."""
        _ensure_pywin32()
        import servicemanager
        import win32serviceutil
        import win32service

        class RavenServiceImpl(win32serviceutil.ServiceFramework):
            _svc_name_ = SERVICE_NAME
            _svc_display_name_ = SERVICE_DISPLAY_NAME
            _svc_description_ = SERVICE_DESCRIPTION

            def __init__(self, args):
                super().__init__(args)
                self._stop_event = threading.Event()

            def SvcStop(self):
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
                self._stop_event.set()

            def SvcDoRun(self):
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, ""),
                )
                self._run_async()

            def _run_async(self):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    from daemon import run_gateway

                    thread = threading.Thread(target=run_gateway, daemon=True)
                    thread.start()
                    self._stop_event.wait()
                except Exception as e:
                    servicemanager.LogErrorMsg(f"Raven service error: {e}")

        win32serviceutil.HandleCommandLine(RavenServiceImpl)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    svc = RavenWindowsService()
    commands = {
        "install": svc.install,
        "start": svc.start,
        "stop": svc.stop,
        "remove": svc.remove,
        "status": svc.status,
        "restart": lambda: (svc.stop(), svc.start()),
    }
    fn = commands.get(cmd)
    if fn:
        fn()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m daemon.windows_service [install|start|stop|remove|status|restart]")


if __name__ == "__main__":
    main()
