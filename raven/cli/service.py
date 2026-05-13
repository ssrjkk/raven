from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

from rich.console import Console


console = Console()

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


def _find_raven() -> str:
    """Return the path to the 'raven' executable."""
    which = os.popen("which raven 2>/dev/null || where raven 2>nul").read().strip()
    if which:
        return which
    return sys.executable + " -m raven.cli.main"


def _find_project_root() -> Path | None:
    """Search upward from cwd or module for pyproject.toml."""
    start = Path(sys.argv[0] if getattr(sys, "frozen", False) else __file__).resolve().parent
    for d in [start, Path.cwd()]:
        for parent in [d] + list(d.parents):
            if (parent / "pyproject.toml").exists():
                return parent
    return None


def service_install():
    """Install Raven as a platform-native service."""
    if IS_WINDOWS:
        _install_windows()
    elif IS_LINUX:
        _install_systemd()
    elif IS_MACOS:
        _install_launchd()
    else:
        console.print("[red]Unsupported platform for service installation[/red]")
        sys.exit(1)


def service_start():
    """Start the Raven service."""
    if IS_WINDOWS:
        _run_python("daemon.windows_service", "start")
    elif IS_LINUX:
        _run_systemctl("start")
    elif IS_MACOS:
        _run_launchctl("load")
    else:
        console.print("[red]Unsupported platform[/red]")


def service_stop():
    """Stop the Raven service."""
    if IS_WINDOWS:
        _run_python("daemon.windows_service", "stop")
    elif IS_LINUX:
        _run_systemctl("stop")
    elif IS_MACOS:
        _run_launchctl("unload")
    else:
        console.print("[red]Unsupported platform[/red]")


def service_status():
    """Show service status."""
    if IS_WINDOWS:
        _run_python("daemon.windows_service", "status")
    elif IS_LINUX:
        _run_systemctl("status")
    elif IS_MACOS:
        _run_launchctl("list")
    else:
        console.print("[red]Unsupported platform[/red]")


def service_remove():
    """Remove the Raven service."""
    if IS_WINDOWS:
        _run_python("daemon.windows_service", "remove")
    elif IS_LINUX:
        _uninstall_systemd()
    elif IS_MACOS:
        _uninstall_launchd()
    else:
        console.print("[red]Unsupported platform[/red]")


def service_restart():
    """Restart the Raven service."""
    service_stop()
    service_start()


# -- Windows ------------------------------------------------------------------


def _install_windows():
    try:
        import win32serviceutil  # noqa: F401
    except ImportError:
        console.print("[red]pywin32 is required. Install: pip install pywin32[/red]")
        sys.exit(1)
    _run_python("daemon.windows_service", "install")
    _run_python("daemon.windows_service", "start")
    console.print("[green]Raven AI Windows service installed and started[/green]")


# -- systemd (Linux) ----------------------------------------------------------


SYSTEMD_SERVICE = textwrap.dedent("""\
    [Unit]
    Description=Raven AI Service
    After=network.target

    [Service]
    Type=simple
    ExecStart={raven_path} start
    Restart=always
    RestartSec=5
    User={user}
    WorkingDirectory={workdir}
    Environment=PYTHONUNBUFFERED=1
    StandardOutput=journal
    StandardError=journal

    [Install]
    WantedBy=multi-user.target
""")


def _install_systemd():
    root = _find_project_root()
    if not root:
        console.print("[red]Cannot find project root (pyproject.toml)[/red]")
        sys.exit(1)
    raven_bin = _find_raven()
    content = SYSTEMD_SERVICE.format(
        raven_path=raven_bin,
        user=os.environ.get("USER", "root"),
        workdir=str(root),
    )
    svc_path = Path("/etc/systemd/system/raven.service")
    try:
        svc_path.write_text(content)
        _run_systemctl("daemon-reload")
        _run_systemctl("enable")
        _run_systemctl("start")
        console.print(f"[green]Raven AI systemd service installed at {svc_path}[/green]")
    except PermissionError:
        console.print("[red]Permission denied. Try: sudo raven service install[/red]")
        sys.exit(1)


def _uninstall_systemd():
    _run_systemctl("stop")
    _run_systemctl("disable")
    svc_path = Path("/etc/systemd/system/raven.service")
    if svc_path.exists():
        svc_path.unlink()
    _run_systemctl("daemon-reload")
    console.print("[green]Raven AI systemd service removed[/green]")


# -- launchd (macOS) ----------------------------------------------------------


LAUNCHD_PLIST = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>com.raven.ai</string>
        <key>ProgramArguments</key>
        <array>
            <string>{raven_path}</string>
            <string>start</string>
        </array>
        <key>WorkingDirectory</key>
        <string>{workdir}</string>
        <key>RunAtLoad</key>
        <true/>
        <key>KeepAlive</key>
        <true/>
        <key>StandardOutPath</key>
        <string>/usr/local/var/log/raven.stdout.log</string>
        <key>StandardErrorPath</key>
        <string>/usr/local/var/log/raven.stderr.log</string>
    </dict>
    </plist>
""")


def _install_launchd():
    root = _find_project_root()
    if not root:
        console.print("[red]Cannot find project root (pyproject.toml)[/red]")
        sys.exit(1)
    raven_bin = _find_raven()
    content = LAUNCHD_PLIST.format(
        raven_path=raven_bin,
        workdir=str(root),
    )
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.raven.ai.plist"
    plist_path.write_text(content)
    _run_launchctl("load", str(plist_path))
    console.print(f"[green]Raven AI launchd service installed at {plist_path}[/green]")


def _uninstall_launchd():
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.raven.ai.plist"
    if plist_path.exists():
        _run_launchctl("unload", str(plist_path))
        plist_path.unlink()
    console.print("[green]Raven AI launchd service removed[/green]")


# -- Helpers ------------------------------------------------------------------


def _run_python(module: str, *args: str):
    cmd = f"{sys.executable} -m {module} {' '.join(args)}"
    rc = os.system(cmd)
    if rc != 0:
        console.print(f"[yellow]Command exited with code {rc}: {cmd}[/yellow]")


def _run_systemctl(action: str):
    os.system(f"systemctl {action} raven.service")


def _run_launchctl(action: str, target: str = "com.raven.ai"):
    os.system(f"launchctl {action} {target}")
