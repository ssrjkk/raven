from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table

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


def _detect_vram_mb() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            vrams = [int(x.strip()) for x in result.stdout.strip().splitlines() if x.strip().isdigit()]
            if vrams:
                return max(vrams)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "path", "win32_videocontroller", "get", "adapterram"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.isdigit():
                        return int(line) // (1024 * 1024)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return 0


def _detect_ram_gb() -> int:
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "OS", "get", "TotalVisibleMemorySize"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.isdigit():
                        return int(line) // (1024 * 1024)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        pass
    return 0


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
                result = subprocess.run(
                    ["sh", str(script_path)],
                    capture_output=True, text=True, timeout=120,
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
    ollama = _find_ollama()
    if not ollama:
        return False
    console.print(f"\nPulling [bold]{model}[/bold] (this may take a while)...")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Downloading {model}...", total=None)
        result = subprocess.run(
            [ollama, "pull", model],
            capture_output=True, text=True, timeout=1800,
        )
        progress.update(task, completed=1)
    if result.returncode != 0:
        console.print(f"[red]Failed to pull {model}: {result.stderr.strip()}[/red]")
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


def _write_raven_json(model: str) -> Path:
    config_dir = Path.cwd()
    tiers = _tier_models_for(model)
    cfg = {
        "version": "0.4.0",
        "llm": {
            "provider": "ollama",
            "default_model": f"ollama/{model}",
            "model_fast": f"ollama/{tiers['fast']}",
            "model_balanced": f"ollama/{tiers['balanced']}",
            "model_quality": f"ollama/{tiers['quality']}",
        },
        "features": {
            "dreaming": True,
            "delegation": True,
            "planner": True,
            "skills": True,
        },
        "security": {
            "dm_policy": "open",
            "web_port": 18888,
        },
        "workspace": "workspace",
        "plugins_dir": "plugins",
        "skills_dir": "workspace/skills",
    }
    path = config_dir / "raven.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    console.print(f"[green]  ✓[/green] {path}")
    return path


def _write_opencode_json(model: str) -> Path:
    config_dir = Path.cwd()
    cfg = {
        "model": f"ollama/{model}",
        "small_model": "ollama/llama3.2:3b",
        "temperature": 0.3,
        "max_tokens": 8192,
        "max_steps": 50,
        "providers": [
            {
                "id": "ollama",
                "name": "Ollama",
                "models": [f"ollama/{model}", "ollama/llama3.2:3b"],
            },
        ],
        "experimental": {
            "dreaming": True,
            "delegation": True,
        },
    }
    for name in ("opencode.json", "ravencode.json"):
        path = config_dir / name
        if not path.exists():
            path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            console.print(f"[green]  ✓[/green] {path}")
            return path
    for name in ("opencode.json", "ravencode.json"):
        path = config_dir / name
        if path.exists():
            return path
    path = config_dir / "opencode.json"
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    console.print(f"[green]  ✓[/green] {path}")
    return path


def _write_env(model: str) -> Path:
    env_path = Path.cwd() / ".env"
    tiers = _tier_models_for(model)
    content = f"""# Raven AI — Free Local Setup
# Auto-generated by `raven setup --free`

# LLM: Ollama (local, no API key required)
RAVEN_LLM_PROVIDER=ollama
RAVEN_DEFAULT_MODEL=ollama/{model}
RAVEN_MODEL_FAST=ollama/{tiers['fast']}
RAVEN_MODEL_BALANCED=ollama/{tiers['balanced']}
RAVEN_MODEL_QUALITY=ollama/{tiers['quality']}
OLLAMA_BASE_URL=http://localhost:11434

# Feature flags
RAVEN_FEATURE_DREAMING=true
RAVEN_FEATURE_DELEGATION=true
RAVEN_FEATURE_PLANNER=true

# Security
WEB_SECRET_KEY={__import__('secrets').token_urlsafe(32)}
"""
    env_path.write_text(content, encoding="utf-8")
    console.print(f"[green]  ✓[/green] {env_path}")
    return env_path


def _ensure_dirs() -> None:
    for d in ("workspace", "workspace/skills", "plugins", "data"):
        Path(d).mkdir(parents=True, exist_ok=True)
        console.print(f"[green]  ✓[/green] {Path(d).resolve()}")


def _print_summary(model: str, ollama_path: str | None) -> None:
    desc = _model_description(model)
    tiers = _tier_models_for(model)
    table = Table(title="Free Local AI Stack — Ready", border_style="green")
    table.add_column("Component", style="cyan")
    table.add_column("Value")
    table.add_row("LLM Provider", "Ollama (100% offline, no API key)")
    table.add_row("Model", f"ollama/{model}")
    table.add_row("Quality", desc or "Auto-selected")
    table.add_row("Fast Tier", f"ollama/{tiers['fast']}")
    table.add_row("Balanced Tier", f"ollama/{tiers['balanced']}")
    table.add_row("Quality Tier", f"ollama/{tiers['quality']}")
    table.add_row("Ollama", ollama_path or "not found")
    table.add_row("Ghost Mode", "Enabled — no external API calls")
    table.add_row("Features", "Dreaming, Delegation, Planner, Skills")
    table.add_row("Configs", "raven.json, opencode.json, .env")
    console.print(table)

    console.print()
    console.print(Panel.fit(
        "[bold]Start Raven:[/bold]  [green]raven start --ghost[/green]\n"
        "[bold]Start coding:[/bold] [green]raven repl[/green]\n"
        "[bold]View status:[/bold]  [green]raven status[/green]",
        border_style="cyan",
    ))


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
            subprocess.Popen([ollama, "serve"], creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen([ollama, "serve"], start_new_session=True)
        import time
        time.sleep(3)
        return True
    except Exception as e:
        console.print(f"[red]Failed to start Ollama: {e}[/red]")
        return False


@click.command()
@click.option("--free", is_flag=True, help="Set up completely free local AI (no API keys)")
@click.option("--model", default=None, help="Force a specific Ollama model (e.g. qwen2.5:32b)")
def setup(free: bool, model: str | None) -> None:
    """Configure Raven for completely free, offline AI with local LLMs"""
    if not free:
        console.print(Panel.fit(
            "[bold]Usage:[/bold]  [green]raven setup --free[/green]\n\n"
            "Sets up the entire stack with local Ollama models — no API keys needed.\n"
            "Auto-detects your GPU and picks the best model for your hardware.",
            border_style="yellow",
        ))
        return

    console.print(Rule(style="bold green"))
    console.print(Panel.fit(
        "[bold]Raven Free Local AI Setup[/bold]\n\n"
        "This will set up a completely free, offline AI stack:\n"
        "  • Install Ollama (if missing)\n"
        "  • Download the best model for your hardware\n"
        "  • Configure Raven, Ravencode, and Ravenflow\n"
        "  • Enable all features (dreaming, delegation, planner)\n"
        "  • No API keys required — 100% free",
        border_style="green",
    ))

    vram = _detect_vram_mb()
    ram = _detect_ram_gb()

    if model:
        chosen = model
    else:
        chosen = _pick_model(vram, ram)

    hw_table = Table(title="Hardware Detection")
    hw_table.add_column("Resource", style="cyan")
    hw_table.add_column("Value")
    hw_table.add_row("GPU VRAM", f"{vram} MB" if vram else "Not detected (CPU mode)")
    hw_table.add_row("System RAM", f"{ram} GB")
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
    if not _pull_model(chosen):
        console.print(f"[yellow]Model pull may have failed. You can run later: ollama pull {chosen}[/yellow]")

    console.print("\n[bold]Generating configuration files...[/bold]")
    _write_raven_json(chosen)
    _write_opencode_json(chosen)
    _write_env(chosen)
    _ensure_dirs()

    console.print()
    _print_summary(chosen, ollama_path)
