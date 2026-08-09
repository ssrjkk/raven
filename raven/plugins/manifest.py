from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger


@dataclass
class PluginManifest:
    """Declared metadata for a plugin directory.

    Optional file ``manifest.json`` next to ``plugin.py``. When absent a
    default manifest is used so existing plugins keep loading unchanged.
    """

    name: str = ""
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    permissions: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    min_raven_version: str = ""
    entry: str = "plugin.py"

    @classmethod
    def from_file(cls, path: Path) -> PluginManifest | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Invalid plugin manifest {}: {}", path, e)
            return None
        if not isinstance(data, dict):
            logger.error("Plugin manifest {} must be a JSON object", path)
            return None
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "0.0.0")),
            description=str(data.get("description", "")),
            author=str(data.get("author", "")),
            permissions=[str(p) for p in data.get("permissions", [])],
            requires=[str(r) for r in data.get("requires", [])],
            min_raven_version=str(data.get("min_raven_version", "")),
            entry=str(data.get("entry", "plugin.py")),
        )

    def validate(self, raven_version: str) -> str | None:
        """Return an error message when the manifest is incompatible, else None."""
        if self.min_raven_version and not _version_ge(raven_version, self.min_raven_version):
            return f"requires raven >= {self.min_raven_version}, current version is {raven_version}"
        return None


def _version_ge(current: str, required: str) -> bool:
    """Semver-ish comparison: major.minor.patch tuples, pre-release suffix ignored."""
    cur = _parse(current)
    req = _parse(required)
    return cur >= req


def _parse(version: str) -> tuple[int, int, int]:
    parts = version.split("+")[0].split("-")[0].split(".")
    nums: list[int] = []
    for p in parts[:3]:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]
