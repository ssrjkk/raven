from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from raven.core.monitor.models import Monitor


async def check_file(monitor: Monitor) -> dict[str, Any]:
    path = Path(monitor.target).expanduser().resolve()
    pattern = monitor.config.get("pattern", "*")
    track_content = monitor.config.get("track_content", False)

    if not path.exists():
        return {"error": f"Path not found: {path}", "changed": False}

    if path.is_file():
        return await _check_single_file(path, track_content)
    else:
        return await _check_directory(path, pattern)


async def _check_single_file(path: Path, track_content: bool) -> dict[str, Any]:
    stat = path.stat()
    result: dict[str, Any] = {
        "path": str(path),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "created": stat.st_ctime,
        "exists": True,
    }

    if track_content:
        content = path.read_bytes()
        result["hash"] = hashlib.md5(content).hexdigest()

    return result


async def _check_directory(path: Path, pattern: str) -> dict[str, Any]:
    files = sorted(path.glob(pattern))
    result: dict[str, Any] = {
        "path": str(path),
        "file_count": len(files),
        "files": [],
        "total_size": 0,
    }

    for f in files[:200]:
        if f.is_file():
            stat = f.stat()
            result["files"].append({
                "name": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
            result["total_size"] += stat.st_size

    return result
