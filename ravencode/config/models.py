from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderConfig:
    id: str = ""
    name: str = ""
    api_key: str = ""
    base_url: str = ""
    models: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelConfig:
    id: str = ""
    provider: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    reasoning_effort: str = ""
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionRuleDef:
    tool: str = ""
    action: str = "ask"
    patterns: list[str] = field(default_factory=list)


@dataclass
class AgentDef:
    name: str = ""
    type: str = "subagent"
    description: str = ""
    prompt: str = ""
    model: str = ""
    temperature: float | None = None
    max_steps: int = 30
    permissions: dict[str, str] = field(default_factory=dict)
    disabled: bool = False
    hidden: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpServerDef:
    name: str = ""
    type: str = "local"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    disabled: bool = False


@dataclass
class LspServerDef:
    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    initialization: dict[str, Any] = field(default_factory=dict)
    disabled: bool = False


@dataclass
class FormatterDef:
    name: str = ""
    command: str = ""
    extensions: list[str] = field(default_factory=list)
    disabled: bool = False


@dataclass
class ThemeColors:
    primary: str = "#00aaff"
    secondary: str = "#ff6600"
    accent: str = "#aa00ff"
    error: str = "#ff4444"
    warning: str = "#ffaa00"
    success: str = "#00cc66"
    info: str = "#33bbff"
    text: str = "#ffffff"
    text_muted: str = "#888888"
    background: str = "#1a1a2e"
    panel: str = "#16213e"
    border: str = "#0f3460"
    diff_add: str = "#00cc66"
    diff_remove: str = "#ff4444"
    diff_add_bg: str = "#003300"
    diff_remove_bg: str = "#330000"

    @classmethod
    def default_dark(cls) -> ThemeColors:
        return cls()

    @classmethod
    def default_light(cls) -> ThemeColors:
        return cls(
            primary="#0066cc",
            secondary="#cc4400",
            accent="#7700cc",
            error="#cc0000",
            warning="#cc8800",
            success="#008844",
            info="#0088cc",
            text="#222222",
            text_muted="#999999",
            background="#ffffff",
            panel="#f5f5f5",
            border="#dddddd",
            diff_add="#008844",
            diff_remove="#cc0000",
            diff_add_bg="#ddffdd",
            diff_remove_bg="#ffdddd",
        )


DEFAULT_THEMES: dict[str, ThemeColors] = {
    "opencode": ThemeColors.default_dark(),
    "tokyonight": ThemeColors(
        primary="#7aa2f7", secondary="#ff9e64", background="#1a1b26", panel="#24283b", border="#414868"
    ),
    "everforest": ThemeColors(
        primary="#83c092", secondary="#e69875", background="#2d353b", panel="#343f44", border="#475258"
    ),
    "catppuccin": ThemeColors(
        primary="#89b4fa", secondary="#fab387", background="#1e1e2e", panel="#313244", border="#45475a"
    ),
    "gruvbox": ThemeColors(
        primary="#83a598", secondary="#fe8019", background="#282828", panel="#3c3836", border="#504945"
    ),
    "nord": ThemeColors(
        primary="#81a1c1", secondary="#d08770", background="#2e3440", panel="#3b4252", border="#4c566a"
    ),
    "ayu": ThemeColors(primary="#39bae6", secondary="#f29668", background="#0a0e14", panel="#0f1920", border="#1a2b36"),
    "kanagawa": ThemeColors(
        primary="#7fb4ca", secondary="#e6c384", background="#1f1f28", panel="#2a2a37", border="#363646"
    ),
    "one-dark": ThemeColors(
        primary="#61afef", secondary="#d19a66", background="#282c34", panel="#2c323c", border="#3e4451"
    ),
    "matrix": ThemeColors(
        primary="#00ff41", secondary="#008f11", background="#000000", panel="#001a00", border="#003300"
    ),
}
