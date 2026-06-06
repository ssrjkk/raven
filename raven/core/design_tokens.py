from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_TOKENS_PATH = Path(__file__).parent.parent.parent / "web" / "src" / "design" / "tokens.json"


class DesignTokens:
    def __init__(self, data: dict[str, Any] | None = None):
        self._data = data or {}

    @classmethod
    def load(cls, path: str | Path | None = None) -> DesignTokens:
        p = Path(path) if path else _TOKENS_PATH
        if not p.exists():
            return cls({})
        with open(p, encoding="utf-8") as f:
            return cls(json.load(f))

    def get(self, *keys: str, default: Any = "") -> Any:
        val: Any = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
                if val is None:
                    return default
            else:
                return default
        return val

    def color(self, *keys: str) -> str:
        return str(self.get("colors", *keys, default="#000000"))

    def spacing(self, key: str) -> str:
        return str(self.get("spacing", key, default="1rem"))

    def font_size(self, key: str) -> str:
        return str(self.get("typography", "font-size", key, default="1rem"))

    def font_family(self, key: str) -> str:
        return str(self.get("typography", "font-family", key, default="sans-serif"))

    def border_radius(self, key: str) -> str:
        return str(self.get("border-radius", key, default="0"))

    def shadow(self, key: str) -> str:
        return str(self.get("shadow", key, default="none"))

    def to_css_vars(self, prefix: str = "--dt") -> str:
        lines: list[str] = [":root {"]
        self._flatten(self._data, prefix, lines)
        lines.append("}")
        return "\n".join(lines)

    def _flatten(self, obj: dict[str, Any], prefix: str, lines: list[str]):
        for key, val in obj.items():
            name = f"{prefix}-{key}" if prefix else key
            if isinstance(val, dict):
                self._flatten(val, name, lines)
            else:
                lines.append(f"  {name}: {val};")

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    @property
    def version(self) -> str:
        return str(self._data.get("version", ""))

    @property
    def colors(self) -> dict[str, Any]:
        return dict(self._data.get("colors", {}))

    @property
    def spacing_map(self) -> dict[str, Any]:
        return dict(self._data.get("spacing", {}))


tokens = DesignTokens.load()
