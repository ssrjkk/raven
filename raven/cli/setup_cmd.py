from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from raven.core.hardware import Hardware, detect
from raven.core.heretic_model import HERETIC_HF_REF, HERETIC_SIZE_GB, preflight

console = Console()

_MODEL_TIER: list[tuple[int, str, str]] = [
    (70_000, "qwen2.5:72b", "Llama 3.1 70B-class — ~85-90% of Claude 3.5 quality"),
    (45_000, "llama3.1:70b", "Meta Llama 3.1 70B — strong general purpose"),
    (32_000, "qwen2.5:32b", "Qwen 2.5 32B — excellent reasoning, ~85% Claude quality"),
    (16_000, "qwen2.5:14b", "Qwen 2.5 14B — solid balance speed/quality"),
    (8_000, "llama3.1:8b", "Llama 3.1 8B — lightweight, 60% Claude quality"),
    (0, "llama3.2:3b", "Llama 3.2 3B — minimal, CPU-friendly"),
]

_GUIDE_URL = "https://ollama.com/download"


def _pick_model(vram_mb: int, ram_gb: int) -> str:
    if vram_mb > 0:
        for threshold, model, _ in _MODEL_TIER:
            if vram_mb >= threshold:
                return model
    if ram_gb >= 32:
        return "llama3.1:8b"
    if ram_gb >= 16:
        return "llama3.2:3b"
    return "llama3.2:1b"


def _model_description(model: str) -> str:
    for _, m, desc in _MODEL_TIER:
        if m == model:
            return desc
    return ""


def _find_ollama() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if platform.system() == "Windows":
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "ollama" / "ollama.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "ollama" / "ollama.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "ollama" / "ollama.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
    return None


def _install_ollama() -> bool:
    system = platform.system()
    console.print("[yellow]Ollama not found. Installing...[/yellow]")
    try:
        if system == "Windows":
            url = "https://ollama.com/download/OllamaSetup.exe"
            import httpx

            installer = Path(os.environ.get("TEMP", ".")) / "OllamaSetup.exe"
            console.print(f"  Downloading from {url}...")
            resp = httpx.get(url, follow_redirects=True, timeout=120)
            installer.write_bytes(resp.content)
            console.print("  Running installer (silent)...")
            subprocess.run([str(installer), "/S"], timeout=60, check=False)
            installer.unlink(missing_ok=True)
            return _find_ollama() is not None
        if system == "Linux":
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
                script_path = Path(tmp.name)
            try:
                resp = httpx.get("https://ollama.com/install.sh", timeout=60)
                resp.raise_for_status()
                script_path.write_bytes(resp.content)
                sh = shutil.which("sh")
                if sh is None:
                    console.print("[red]No sh on PATH; install Ollama from https://ollama.com/download[/red]")
                    return False
                result = subprocess.run(
                    [sh, str(script_path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                if result.returncode == 0:
                    return _find_ollama() is not None
                console.print(f"[red]Install failed: {result.stderr}[/red]")
                return False
            finally:
                script_path.unlink(missing_ok=True)
        if system == "Darwin":
            console.print("[yellow]macOS: install Ollama from https://ollama.com/download[/yellow]")
            console.print("  Or: brew install ollama")
            return False
    except Exception as e:
        console.print(f"[red]Install error: {e}[/red]")
        return False
    return False


def _pull_model(model: str) -> bool:
    """Pull with Ollama's own progress on the terminal — 5.63 GB behind a spinner reads as a hang."""
    ollama = _find_ollama()
    if not ollama:
        return False
    console.print(f"\nPulling [bold]{model}[/bold] (this may take a while)...")
    try:
        result = subprocess.run([ollama, "pull", model], timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        console.print(
            f"[red]The pull passed 30 min and was stopped.[/red] "
            f"Ollama keeps what it downloaded; resume with: ollama pull {model}"
        )
        return False
    except OSError as exc:
        console.print(f"[red]Could not run {ollama}: {exc}[/red]")
        return False
    if result.returncode != 0:
        console.print(f"[red]Failed to pull {model} (exit {result.returncode}).[/red] Retry with: ollama pull {model}")
        return False
    return True


def _tier_models_for(primary: str) -> dict[str, str]:
    known = {
        "qwen2.5:72b": {"fast": "llama3.2:3b", "balanced": "llama3.1:8b", "quality": "qwen2.5:72b"},
        "llama3.1:70b": {"fast": "llama3.2:3b", "balanced": "llama3.1:8b", "quality": "llama3.1:70b"},
        "qwen2.5:32b": {"fast": "llama3.2:3b", "balanced": "qwen2.5:14b", "quality": "qwen2.5:32b"},
        "qwen2.5:14b": {"fast": "llama3.2:3b", "balanced": "qwen2.5:14b", "quality": "qwen2.5:14b"},
        "llama3.1:8b": {"fast": "llama3.2:3b", "balanced": "llama3.1:8b", "quality": "llama3.1:8b"},
        "llama3.2:3b": {"fast": "llama3.2:3b", "balanced": "llama3.2:3b", "quality": "llama3.2:3b"},
        "llama3.2:1b": {"fast": "llama3.2:1b", "balanced": "llama3.2:1b", "quality": "llama3.2:1b"},
    }
    return known.get(primary, {"fast": primary, "balanced": primary, "quality": primary})


def _write_json_config(path: Path, fresh: dict[str, Any], owned: Callable[[dict[str, Any]], None]) -> Path:
    """Create a config file, or update only the keys this command owns in the one that exists.

    Both files used to be overwritten wholesale, which deleted the channel tokens kept in ``raven.json``
    and the providers, agents and MCP servers an operator added to ``opencode.json`` — and left
    ``opencode.json`` naming the previous model after a switch, so ravencode kept calling it. A file
    that does not parse as plain JSON is left alone: ravencode also reads JSONC, and comments and
    trailing commas do not survive a round trip through :mod:`json`.
    """
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = None
        if not isinstance(cfg, dict):
            console.print(
                f"[yellow]  ![/yellow] {path} is not plain JSON — left untouched, edit it to change the model"
            )
            return path
        owned(cfg)
    else:
        cfg = fresh
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    console.print(f"[green]  ✓[/green] {path}")
    return path


_FEATURE_FLAGS = {"dreaming": True, "delegation": True, "planner": True, "skills": True}


def _write_raven_json(model: str) -> Path:
    tiers = _tier_models_for(model)
    llm = {
        "provider": "ollama",
        "default_model": f"ollama/{model}",
        "model_fast": f"ollama/{tiers['fast']}",
        "model_balanced": f"ollama/{tiers['balanced']}",
        "model_quality": f"ollama/{tiers['quality']}",
    }

    def owned(cfg: dict[str, Any]) -> None:
        cfg.setdefault("llm", {}).update(llm)
        if cfg.pop("features", None) is not None:
            console.print(
                "[yellow]  ![/yellow] raven.json `features` moved to .raven/features.yaml — the flags are read there"
            )

    return _write_json_config(
        Path.cwd() / "raven.json",
        {
            "version": "0.4.8",
            "llm": llm,
            "security": {"dm_policy": "open", "web_port": 18888},
            "workspace": "workspace",
            "paths": {
                "skills": ["workspace/skills"],
                "commands": [".raven/commands"],
                "rules": [".raven/rules"],
                "agents": [".raven/agents"],
                "plugins": ["plugins"],
                "hooks": [".raven/hooks"],
            },
        },
        owned,
    )


def _write_features_yaml() -> Path:
    """Turn the free stack's toggles on in the file the flag loader reads.

    `raven.json` has no features reader: `raven/core/features.py` takes the flags from
    `.raven/features.yaml` and lets `RAVEN_FEATURE_*` have the last word, so the switches this command
    used to write into `raven.json` left dreaming off while the summary said it was on.
    """
    path = Path.cwd() / ".raven" / "features.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if not lines:
        lines = [
            "# Feature toggles read by the gateway at startup.",
            "# RAVEN_FEATURE_<NAME> in the environment overrides anything written here.",
            "features:",
        ]
    head = next((i for i, line in enumerate(lines) if line.strip() == "features:"), None)
    if head is None:
        lines = [*lines, "features:"]
        head = len(lines) - 1
    end = head + 1
    while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
        end += 1
    entries = {line.partition(":")[0].strip(): i for i, line in enumerate(lines[head + 1 : end], head + 1)}
    missing: list[str] = []
    for key, value in _FEATURE_FLAGS.items():
        text = f"  {key}: {str(value).lower()}"
        if key in entries:
            lines[entries[key]] = text
        else:
            missing.append(text)
    if missing:
        lines[end:end] = missing
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]  ✓[/green] {path}")
    return path


def _write_opencode_json(model: str) -> Path:
    """Point the coding agent at the chosen model; ravencode reads ``opencode.json`` first and stops.

    No ``ravencode.json`` is written: ravencode's resolver takes the first of ``opencode.json``,
    ``opencode.jsonc``, ``ravencode.json``, ``ravencode.jsonc`` it finds (ravencode/config/loader.py),
    so a copy made next to an existing ``opencode.json`` is a file nothing ever reads.
    """
    tiers = _tier_models_for(model)
    default = f"ollama/{model}"
    small = f"ollama/{tiers['fast']}"

    def owned(cfg: dict[str, Any]) -> None:
        cfg["model"] = default
        cfg["small_model"] = small
        providers = cfg.setdefault("providers", [])
        if isinstance(providers, list):
            for entry in providers:
                if isinstance(entry, dict) and entry.get("id") == "ollama":
                    entry["models"] = [default, small]
                    break
            else:
                providers.append({"id": "ollama", "name": "Ollama", "models": [default, small]})

    return _write_json_config(
        Path.cwd() / "opencode.json",
        {
            "model": default,
            "small_model": small,
            "temperature": 0.3,
            "max_tokens": 8192,
            "max_steps": 50,
            "providers": [{"id": "ollama", "name": "Ollama", "models": [default, small]}],
            "experimental": {"dreaming": True, "delegation": True},
        },
        owned,
    )


def _write_env(model: str, env_path: Path | None = None) -> Path:
    """Point the env file at the local tiers, leaving every other line in it alone.

    The file carries the operator's keys: rewriting it wholesale used to drop them and to rotate
    ``WEB_SECRET_KEY`` on every run, which logs out every session and invalidates every stored token.
    """
    from raven.core.config import read_env_value, write_env_value

    path = env_path or Path.cwd() / ".env"
    tiers = _tier_models_for(model)
    if not path.exists():
        path.write_text(
            "# Raven AI — local configuration.\n"
            "# The ollama/ prefix on a model name is what selects the provider; there is no separate switch.\n",
            encoding="utf-8",
        )
    write_env_value("DEFAULT_MODEL", f"ollama/{model}", path)
    write_env_value("MODEL_FAST", f"ollama/{tiers['fast']}", path)
    write_env_value("MODEL_BALANCED", f"ollama/{tiers['balanced']}", path)
    write_env_value("MODEL_QUALITY", f"ollama/{tiers['quality']}", path)
    write_env_value("OLLAMA_BASE_URL", "http://localhost:11434", path)
    if read_env_value("WEB_SECRET_KEY", path) is None:
        import secrets

        write_env_value("WEB_SECRET_KEY", secrets.token_urlsafe(32), path)
    console.print(f"[green]  ✓[/green] {path}")
    return path


def _ensure_dirs() -> None:
    for d in ("workspace", "workspace/skills", "plugins", "data"):
        Path(d).mkdir(parents=True, exist_ok=True)
        console.print(f"[green]  ✓[/green] {Path(d).resolve()}")


def _print_summary(model: str, ollama_path: str | None, pulled: bool) -> None:
    from raven.core.features import FeatureFlags

    desc = _model_description(model)
    tiers = _tier_models_for(model)
    enabled = FeatureFlags.load().enabled_list()
    title = "Free Local AI Stack — Ready" if pulled else "Free Local AI Stack — configured, weights missing"
    table = Table(title=title, border_style="green" if pulled else "yellow")
    table.add_column("Component", style="cyan")
    table.add_column("Value")
    table.add_row("LLM Provider", "Ollama (100% offline, no API key)")
    table.add_row("Model", f"ollama/{model}")
    table.add_row("Weights", "pulled" if pulled else f"NOT pulled — run: ollama pull {model}")
    table.add_row("Quality", desc or "Auto-selected")
    table.add_row("Fast Tier", f"ollama/{tiers['fast']}")
    table.add_row("Balanced Tier", f"ollama/{tiers['balanced']}")
    table.add_row("Quality Tier", f"ollama/{tiers['quality']}")
    table.add_row("Ollama", ollama_path or "not found")
    table.add_row("Ghost Mode", "Enabled — no external API calls")
    table.add_row("Features", ", ".join(enabled) if enabled else "none enabled")
    table.add_row("Configs", "raven.json, opencode.json, .env, .raven/features.yaml")
    console.print(table)

    console.print()
    console.print(
        Panel.fit(
            "[bold]Start Raven:[/bold]  [green]raven start --ghost[/green]\n"
            "[bold]Start coding:[/bold] [green]raven repl[/green]\n"
            "[bold]View status:[/bold]  [green]raven status[/green]",
            border_style="cyan",
        )
    )


def _ollama_serve() -> bool:
    ollama = _find_ollama()
    if not ollama:
        return False
    try:
        import httpx

        resp = httpx.get("http://localhost:11434/api/tags", timeout=3)
        return resp.is_success
    except Exception:
        console.print("[dim]Ollama not responding, starting service...[/dim]")
    try:
        console.print("[yellow]Starting Ollama service...[/yellow]")
        if platform.system() == "Windows":
            detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            subprocess.Popen([ollama, "serve"], creationflags=detached)
        else:
            subprocess.Popen([ollama, "serve"], start_new_session=True)
        import time

        time.sleep(3)
        return True
    except Exception as e:
        console.print(f"[red]Failed to start Ollama: {e}[/red]")
        return False


def _experimental_choice(hw: Hardware, confirmed: bool, vram_mb: int, ram_gb: int) -> str:
    """Return the model ``--experimental`` asked for, but only once the download is actually agreed to.

    The switch and the weights have to land together: pointing ``DEFAULT_MODEL`` at a 5.63 GB model that
    was never pulled leaves a freshly set-up box calling a model Ollama does not have. So a decline —
    interactive or scripted — falls back to the model this hardware runs and pulls that one, which is
    what ``setup --free`` does by default, and says so before the download starts. The experimental one
    stays available through ``raven models enable-heretic``.
    """
    if confirmed:
        return HERETIC_HF_REF
    console.print(f"[bold]{HERETIC_HF_REF}[/bold] — {HERETIC_SIZE_GB:.2f} GB\n{hw.summary()}")
    if not sys.stdin.isatty():
        console.print(
            f"[red]Not downloading {HERETIC_SIZE_GB:.2f} GB without a yes[/red] — "
            f"re-run with --yes, or later: raven models enable-heretic"
        )
    elif not click.confirm(f"Download {HERETIC_SIZE_GB:.2f} GB into Ollama?", default=False):
        console.print("[yellow]Download declined.[/yellow]")
    else:
        return HERETIC_HF_REF
    fallback = _pick_model(vram_mb, ram_gb)
    console.print(
        f"[yellow]Configuring {fallback}, which this hardware runs, and pulling it instead.[/yellow] "
        "Switch the experimental one on later: raven models enable-heretic"
    )
    return fallback


@click.command()
@click.option("--free", is_flag=True, help="Set up completely free local AI (no API keys)")
@click.option("--model", default=None, help="Force a specific Ollama model (e.g. qwen2.5:32b)")
@click.option(
    "--experimental",
    is_flag=True,
    help=f"Use the bundled free experimental model instead of the auto-picked one (~{HERETIC_SIZE_GB:.2f} GB)",
)
@click.option(
    "--yes",
    "confirmed",
    is_flag=True,
    help="Accept the model download instead of being asked (for scripted runs)",
)
def setup(free: bool, model: str | None, experimental: bool, confirmed: bool) -> None:
    """Configure Raven for completely free, offline AI with local LLMs"""
    if not free:
        console.print(
            Panel.fit(
                "[bold]Usage:[/bold]  [green]raven setup --free[/green]\n\n"
                "Sets up the entire stack with local Ollama models — no API keys needed.\n"
                "Auto-detects your GPU and picks the best model for your hardware.\n"
                "Add [green]--experimental[/green] for the bundled uncensored 9B, [green]--model NAME[/green] to pick one.",
                border_style="yellow",
            )
        )
        return

    console.print(Rule(style="bold green"))
    console.print(
        Panel.fit(
            "[bold]Raven Free Local AI Setup[/bold]\n\n"
            "This will set up a completely free, offline AI stack:\n"
            "  • Install Ollama (if missing)\n"
            "  • Download the best model for your hardware\n"
            "  • Configure Raven, Ravencode, and Ravenflow\n"
            "  • Enable all features (dreaming, delegation, planner)\n"
            "  • No API keys required — 100% free",
            border_style="green",
        )
    )

    hw = detect()
    vram = hw.vram_mb
    ram = int(hw.ram_total_gb)

    if model:
        chosen = model
    elif experimental:
        blockers = preflight(hw)
        if blockers:
            console.print(f"[red]--experimental refused:[/red] {HERETIC_HF_REF} needs more than this box has")
            for blocker in blockers:
                console.print(f"  [red]x[/red] {blocker}")
            console.print("[dim]Re-run without --experimental for the model this hardware can run.[/dim]")
            raise SystemExit(1)
        chosen = _experimental_choice(hw, confirmed, vram, ram)
    else:
        chosen = _pick_model(vram, ram)

    hw_table = Table(title="Hardware Detection")
    hw_table.add_column("Resource", style="cyan")
    hw_table.add_column("Value")
    hw_table.add_row("GPU VRAM", f"{vram} MB" if vram else "Not detected (CPU mode)")
    hw_table.add_row("System RAM", f"{ram} GB ({hw.ram_free_gb:.1f} GB free now)")
    hw_table.add_row("Disk for models", f"{hw.disk_free_gb:.1f} GB free")
    hw_table.add_row("Selected Model", f"[bold]{chosen}[/bold]")
    hw_table.add_row("Platform", platform.system())
    console.print(hw_table)

    if vram == 0:
        console.print("[yellow]No NVIDIA GPU detected. Will use CPU — slower but works.[/yellow]")

    ollama_path = _find_ollama()
    if not ollama_path:
        console.print()
        if not _install_ollama():
            console.print(f"[red]Please install Ollama manually from {_GUIDE_URL}[/red]")
            raise SystemExit(1)
        ollama_path = _find_ollama()

    _ollama_serve()
    console.print()
    pulled = _pull_model(chosen)
    if not pulled:
        console.print(f"[yellow]The weights are not on this machine yet. Finish with: ollama pull {chosen}[/yellow]")

    console.print("\n[bold]Generating configuration files...[/bold]")
    _write_raven_json(chosen)
    _write_opencode_json(chosen)
    _write_env(chosen)
    _write_features_yaml()
    _ensure_dirs()

    console.print()
    _print_summary(chosen, ollama_path, pulled)
    if not pulled:
        raise SystemExit(1)
