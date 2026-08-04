from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class CommandResponse(BaseModel):
    id: str
    label: str
    description: str
    icon: str  # 'code', 'db', 'file'
    category: str
    action_endpoint: str | None = None


class ThemePrefs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    accent_color: str = Field(alias="accentColor")


class ThemeSchemeRequest(BaseModel):
    prompt: str
    seed: str | None = None
    use_llm: bool = True


class ThemeScheme(BaseModel):
    name: str
    description: str
    accent: str
    palette: dict[str, dict[str, str]]


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_DEFAULT_ACCENT = "#7c3aed"
_DATA_DIR_OVERRIDE: str | None = None


def _data_dir() -> Path:
    if _DATA_DIR_OVERRIDE is not None:
        return Path(_DATA_DIR_OVERRIDE)
    return Path(os.getenv("RAVEN_DATA_DIR", "data"))


def _theme_prefs_path() -> Path:
    return _data_dir() / "theme_prefs.json"


def _load_theme_prefs() -> dict[str, str]:
    path = _theme_prefs_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("accentColor"), str):
            return {"accentColor": raw["accentColor"]}
    except (OSError, json.JSONDecodeError):
        pass
    return {"accentColor": _DEFAULT_ACCENT}


def _save_theme_prefs(prefs: ThemePrefs) -> None:
    path = _theme_prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prefs.model_dump(by_alias=True), indent=2), encoding="utf-8")


def _is_valid_hex(value: str) -> bool:
    return _HEX_RE.fullmatch(value) is not None


def _hsl_to_hex(h: float, s: float, lightness: float) -> str:
    h = h % 360
    c = (1 - abs(2 * lightness - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = lightness - c / 2
    if h < 60:
        r, g, b = c, x, 0.0
    elif h < 120:
        r, g, b = x, c, 0.0
    elif h < 180:
        r, g, b = 0.0, c, x
    elif h < 240:
        r, g, b = 0.0, x, c
    elif h < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x

    def to_byte(v: float) -> int:
        return round(min(max(v + m, 0), 1) * 255)

    return f"#{to_byte(r):02x}{to_byte(g):02x}{to_byte(b):02x}"


def _hex_to_rgba(value: str, alpha: float) -> str:
    r = int(value[1:3], 16)
    g = int(value[3:5], 16)
    b = int(value[5:7], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _deterministic_palette(seed: str) -> dict[str, dict[str, str]]:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") % 360
    hue2 = (hue + 30) % 360
    accent = _hsl_to_hex(hue, 0.78, 0.58)
    accent_hover = _hsl_to_hex(hue, 0.85, 0.66)
    accent_active = _hsl_to_hex(hue, 0.72, 0.50)
    accent_link = _hsl_to_hex(hue, 0.78, 0.66)
    accent_link_hover = _hsl_to_hex(hue, 0.85, 0.74)
    return {
        "bg": {
            "primary": _hsl_to_hex(hue2, 0.20, 0.09),
            "secondary": _hsl_to_hex(hue2, 0.20, 0.13),
            "tertiary": _hsl_to_hex(hue2, 0.18, 0.16),
            "hover": _hsl_to_hex(hue2, 0.18, 0.18),
            "active": _hsl_to_hex(hue2, 0.20, 0.22),
            "inverse": "#ffffff",
        },
        "surface": {
            "default": _hsl_to_hex(hue2, 0.20, 0.13),
            "elevated": _hsl_to_hex(hue2, 0.18, 0.16),
            "card": _hsl_to_hex(hue2, 0.20, 0.12),
            "tooltip": _hsl_to_hex(hue2, 0.18, 0.19),
            "modal": _hsl_to_hex(hue2, 0.20, 0.13),
        },
        "accent": {
            "default": accent,
            "hover": accent_hover,
            "active": accent_active,
            "muted": _hex_to_rgba(accent, 0.15),
            "subtle": _hex_to_rgba(accent, 0.08),
        },
        "text": {
            "primary": _hsl_to_hex(hue2, 0.22, 0.93),
            "secondary": _hsl_to_hex(hue2, 0.14, 0.70),
            "tertiary": _hsl_to_hex(hue2, 0.10, 0.50),
            "inverse": "#0a0b0d",
            "link": accent_link,
            "link-hover": accent_link_hover,
        },
        "border": {
            "default": _hsl_to_hex(hue2, 0.14, 0.20),
            "hover": _hsl_to_hex(hue2, 0.14, 0.28),
            "focus": accent,
            "muted": _hsl_to_hex(hue2, 0.14, 0.15),
        },
        "status": {
            "success": "#22c55e",
            "warning": "#eab308",
            "error": "#ef4444",
            "info": "#3b82f6",
            "success-bg": "rgba(34, 197, 94, 0.1)",
            "warning-bg": "rgba(234, 179, 8, 0.1)",
            "error-bg": "rgba(239, 68, 68, 0.1)",
            "info-bg": "rgba(59, 130, 246, 0.1)",
        },
    }


def _coerce_palette(raw: object) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        return result
    for group, value in raw.items():
        if not isinstance(group, str) or not isinstance(value, dict):
            continue
        group_map = {
            key: color
            for key, color in value.items()
            if isinstance(key, str) and isinstance(color, str) and _is_valid_hex(color)
        }
        if group_map:
            result[group] = group_map
    return result


def _complete_palette(base: dict[str, dict[str, str]], overrides: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for group, colors in base.items():
        group_map = dict(colors)
        if group in overrides:
            for key, color in overrides[group].items():
                if key in group_map and _is_valid_hex(color):
                    group_map[key] = color
        merged[group] = group_map
    return merged


async def _llm_palette(prompt: str) -> dict[str, dict[str, str]] | None:
    try:
        from raven.core.llm import LLMRouter

        system = (
            "You generate cohesive dark-mode UI color schemes as strict JSON. "
            'Return ONLY a JSON object with groups "bg", "surface", "accent", "text", "border", "status". '
            "Every color MUST be a 6-digit hex like #a1b2c3. "
            'bg: primary/secondary/tertiary/inverse; surface: default/elevated/card/tooltip/modal; '
            "accent: default/hover/active; text: primary/secondary/tertiary/link; border: default/hover/focus; "
            "status: success/warning/error/info. Colors must form a harmonious accessible palette."
        )
        user = f"Design a color scheme for: {prompt}"
        router = LLMRouter()
        resp = await router.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model="",
        )
        text = resp.content
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        raw = json.loads(text[start : end + 1])
        return _coerce_palette(raw) or None
    except Exception:
        return None


async def generate_theme_scheme(prompt: str, seed: str | None = None, use_llm: bool = True) -> ThemeScheme:
    effective_seed = seed if seed else prompt
    palette = _deterministic_palette(effective_seed)
    if use_llm:
        llm_palette = await _llm_palette(prompt)
        if llm_palette is not None:
            palette = _complete_palette(palette, llm_palette)
    accent = palette["accent"]["default"]
    name = f"AI · {prompt.strip()[:40]}" if prompt.strip() else "Raven AI"
    return ThemeScheme(
        name=name,
        description=prompt.strip() or "AI-generated color scheme",
        accent=accent,
        palette=palette,
    )


def _detect_project_state() -> str:
    workspace = Path(os.getenv("RAVEN_WORKSPACE", "workspace"))
    if not workspace.is_dir():
        return "empty"
    try:
        py = list(workspace.rglob("*.py"))
        ts = list(workspace.rglob("*.ts"))
        tsx = list(workspace.rglob("*.tsx"))
        rs = list(workspace.rglob("*.rs"))
        go = list(workspace.rglob("*.go"))
    except PermissionError:
        return "has_code"
    total = len(py) + len(ts) + len(tsx) + len(rs) + len(go)
    return "empty" if total == 0 else "has_code"


def create_commands_router(data_dir: str | None = None) -> APIRouter:
    global _DATA_DIR_OVERRIDE
    if data_dir is not None:
        _DATA_DIR_OVERRIDE = data_dir

    router = APIRouter(prefix="/api/v1/commands", tags=["commands"])

    @router.get("/contextual", response_model=list[CommandResponse])
    async def get_contextual_commands():
        project_state = _detect_project_state()

        commands: list[CommandResponse] = []

        if project_state == "empty":
            commands.append(
                CommandResponse(
                    id="scaffold-api",
                    label="Создать FastAPI структуру",
                    description="Сгенерировать boilerplate для нового API",
                    icon="code",
                    category="ai",
                    action_endpoint="/api/v1/ai/scaffold",
                )
            )

        commands.append(
            CommandResponse(
                id="generate-tests",
                label="Сгенерировать тесты",
                description="AI напишет unit-тесты для текущих модулей",
                icon="code",
                category="ai",
                action_endpoint="/api/v1/ai/generate-tests",
            )
        )

        return commands

    @router.get("/theme", response_model=ThemePrefs)
    async def get_theme() -> ThemePrefs:
        prefs = _load_theme_prefs()
        return ThemePrefs(accentColor=prefs["accentColor"])

    @router.post("/theme", response_model=ThemePrefs)
    async def save_theme(prefs: ThemePrefs) -> ThemePrefs:
        if not _is_valid_hex(prefs.accent_color):
            raise HTTPException(status_code=400, detail="accentColor must be a #rrggbb hex value")
        _save_theme_prefs(prefs)
        return prefs

    @router.post("/theme/generate", response_model=ThemeScheme)
    async def generate_theme(body: ThemeSchemeRequest) -> ThemeScheme:
        if not body.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt must not be empty")
        scheme = await generate_theme_scheme(body.prompt, body.seed, body.use_llm)
        _save_theme_prefs(ThemePrefs(accentColor=scheme.accent))
        return scheme

    return router
