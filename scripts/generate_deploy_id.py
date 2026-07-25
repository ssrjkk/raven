"""Generate raven/core/_deploy.py with a unique deploy ID and timestamp.

Called automatically by pre-commit hook. Each commit produces a distinct build.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_GIT = shutil.which("git") or "git"


def _git_describe() -> str:
    try:
        return subprocess.check_output(
            [_GIT, "describe", "--always", "--dirty", "--long"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
    except Exception:
        return "unknown"


def _git_origin() -> str:
    try:
        return subprocess.check_output(
            [_GIT, "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
    except Exception:
        return "unknown"


def _git_branch() -> str:
    try:
        return subprocess.check_output(
            [_GIT, "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
    except Exception:
        return "unknown"


def main():
    deploy_id = _git_describe()
    origin = _git_origin()
    branch = _git_branch()
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")

    out = Path(__file__).resolve().parent.parent / "raven" / "core" / "_deploy.py"
    out.write_text(
        "# Auto-generated deploy ID - do not edit manually.\n"
        f"DEPLOY_ID = {deploy_id!r}\n"
        f"DEPLOY_ORIGIN = {origin!r}\n"
        f"DEPLOY_BRANCH = {branch!r}\n"
        f"DEPLOY_TIMESTAMP = {timestamp!r}\n"
    )
    print(f"[watermark] wrote {out}")
    print(f"[watermark]   DEPLOY_ID={deploy_id}")
    print(f"[watermark]   ORIGIN={origin}")
    print(f"[watermark]   BRANCH={branch}")


if __name__ == "__main__":
    main()
    sys.exit(0)
