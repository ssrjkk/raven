from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections import Counter
from pathlib import Path
from typing import TypedDict

from fastapi import APIRouter


class LangStats(TypedDict):
    files: int
    lines: int
    code: int


class SummaryDict(TypedDict):
    total_files: int
    total_lines: int
    total_code: int
    languages: int


class DepEntry(TypedDict):
    name: str
    count: int


class DependenciesDict(TypedDict):
    total_unique: int
    top_modules: list[DepEntry]


_workspace: str = ""


def set_workspace(path: str) -> None:
    global _workspace
    _workspace = path


def _get_workspace() -> Path:
    ws = _workspace or os.getenv("RAVEN_WORKSPACE", "workspace") or "workspace"
    return Path(ws)


_FILE_PATTERNS: list[tuple[str, str]] = [
    ("Python", "**/*.py"),
    ("TypeScript", "**/*.ts"),
    ("TSX", "**/*.tsx"),
    ("JavaScript", "**/*.js"),
    ("JSX", "**/*.jsx"),
    ("Rust", "**/*.rs"),
    ("Go", "**/*.go"),
    ("YAML", "**/*.{yml,yaml}"),
    ("JSON", "**/*.json"),
    ("Markdown", "**/*.md"),
    ("CSS", "**/*.css"),
    ("Shell", "**/*.{sh,bat,ps1}"),
    ("Docker", "**/Dockerfile*"),
    ("SQL", "**/*.sql"),
    ("HTML", "**/*.html"),
]

_LANG_COMMENT_PATTERNS: dict[str, list[str]] = {
    "Python": ["#"],
    "TypeScript": ["//", "/*"],
    "Rust": ["//", "/*"],
    "Go": ["//", "/*"],
}


def _count_lines(path: Path) -> tuple[int, int]:
    with contextlib.suppress(Exception):
        text = path.read_text("utf-8", errors="replace")
        lines = text.splitlines()
        code = 0
        in_block = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if not in_block:
                if stripped.startswith("/*"):
                    in_block = True
                    if "*/" in stripped:
                        in_block = False
                    continue
                if stripped.startswith(("#", "//")):
                    continue
                code += 1
            else:
                if "*/" in stripped:
                    in_block = False
        return len(lines), code
    return 0, 0


def _scan_code_stats(ws: Path) -> dict[str, LangStats]:
    by_lang: dict[str, LangStats] = {}
    for lang, pattern in _FILE_PATTERNS:
        files = list(ws.rglob(pattern))
        if not files:
            continue
        total_lines = 0
        total_code = 0
        for f in files:
            lines, code = _count_lines(f)
            total_lines += lines
            total_code += code
        by_lang[lang] = {"files": len(files), "lines": total_lines, "code": total_code}
    return by_lang


_IMPORT_RE = re.compile(r"^(?:import|from)\s+(\S+)", re.MULTILINE)
_TS_IMPORT_RE = re.compile(r"import\s+(?:\{[^}]*\}|[^;{]+)\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE | re.UNICODE)


def _scan_dependencies(ws: Path) -> DependenciesDict:
    raw: Counter[str] = Counter()
    for f in ws.rglob("*.py"):
        with contextlib.suppress(Exception):
            raw.update(_IMPORT_RE.findall(f.read_text("utf-8", errors="replace")))
    for f in list(ws.rglob("*.ts")) + list(ws.rglob("*.tsx")):
        with contextlib.suppress(Exception):
            raw.update(_TS_IMPORT_RE.findall(f.read_text("utf-8", errors="replace")))
    modules = [m.split(".")[0] for m in raw if not m.startswith(".") and not m.startswith("node_modules")]
    top = Counter(modules).most_common(30)
    return {
        "total_unique": len(set(modules)),
        "top_modules": [{"name": m, "count": c} for m, c in top],
    }


def _scan_recent_activity(ws: Path) -> dict[str, int]:
    from datetime import UTC, datetime, timedelta

    by_day: Counter[str] = Counter()
    for f in ws.rglob("*"):
        if f.is_file() and not any(p.startswith(".") or p == "node_modules" or p == "__pycache__" for p in f.parts):
            with contextlib.suppress(Exception):
                mtime = f.stat().st_mtime
                age = datetime.now(UTC) - datetime.fromtimestamp(mtime, tz=UTC)
                if age < timedelta(days=1):
                    by_day["today"] += 1
                elif age < timedelta(days=7):
                    by_day["this_week"] += 1
                elif age < timedelta(days=30):
                    by_day["this_month"] += 1
    return dict(by_day)


def create_project_metrics_router() -> APIRouter:
    router = APIRouter(prefix="/api/metrics", tags=["metrics"])

    @router.get("/project")
    async def get_project_metrics():
        ws = _get_workspace()
        if not ws.is_dir():
            return {
                "code_stats": {},
                "summary": {"total_files": 0, "total_lines": 0, "total_code": 0, "languages": 0},
                "dependencies": {"total_unique": 0, "top_modules": []},
                "activity": {},
            }
        code_stats, deps, activity = await asyncio.gather(
            asyncio.to_thread(_scan_code_stats, ws),
            asyncio.to_thread(_scan_dependencies, ws),
            asyncio.to_thread(_scan_recent_activity, ws),
        )
        total_files = sum(v["files"] for v in code_stats.values())
        total_lines = sum(v["lines"] for v in code_stats.values())
        total_code = sum(v["code"] for v in code_stats.values())
        return {
            "code_stats": code_stats,
            "summary": {
                "total_files": total_files,
                "total_lines": total_lines,
                "total_code": total_code,
                "languages": len(code_stats),
            },
            "dependencies": deps,
            "activity": activity,
        }

    return router
