from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from raven.core.routine.models import Routine


async def organize_files(routine: Routine) -> str:
    config = routine.config
    watch_dir = config.get("watch_dir", "~/Downloads")
    rules = config.get("rules", [])

    base = Path(watch_dir).expanduser().resolve()
    if not base.is_dir():
        return f"Directory not found: {base}"

    if not rules:
        rules = _default_rules()

    moved = 0
    for item in base.iterdir():
        if not item.is_file():
            continue
        for rule in rules:
            pattern = rule.get("pattern", "*")
            dest = rule.get("dest", "")
            if not dest:
                continue
            if item.match(pattern):
                dest_dir = Path(dest).expanduser().resolve()
                dest_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(item), str(dest_dir / item.name))
                    moved += 1
                except shutil.Error:
                    pass
                break

    if moved:
        return f"Organized {moved} files in {base.name}"
    return f"No files to organize in {base.name}"


def _default_rules() -> list[dict[str, Any]]:
    return [
        {"pattern": "*.pdf", "dest": "~/Documents/PDFs"},
        {"pattern": "*.jpg", "dest": "~/Pictures"},
        {"pattern": "*.jpeg", "dest": "~/Pictures"},
        {"pattern": "*.png", "dest": "~/Pictures"},
        {"pattern": "*.gif", "dest": "~/Pictures"},
        {"pattern": "*.mp4", "dest": "~/Videos"},
        {"pattern": "*.mov", "dest": "~/Videos"},
        {"pattern": "*.mp3", "dest": "~/Music"},
        {"pattern": "*.zip", "dest": "~/Downloads/Archives"},
        {"pattern": "*.tar.gz", "dest": "~/Downloads/Archives"},
        {"pattern": "*.dmg", "dest": "~/Downloads/Installers"},
        {"pattern": "*.exe", "dest": "~/Downloads/Installers"},
        {"pattern": "*.msi", "dest": "~/Downloads/Installers"},
        {"pattern": "*.doc", "dest": "~/Documents"},
        {"pattern": "*.docx", "dest": "~/Documents"},
        {"pattern": "*.xls", "dest": "~/Documents"},
        {"pattern": "*.xlsx", "dest": "~/Documents"},
    ]
