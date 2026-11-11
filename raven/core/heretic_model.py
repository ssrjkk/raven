"""The bundled free experimental model: uncensored Qwen3.5-9B (heretic).

Nothing here downloads anything unless an operator asks for it. The module owns three things: the
reference to the weights, the numeric answer to "can this machine run it", and the switch that makes
it the model Raven actually calls.

Out-of-the-box flow without vendoring 5.63 GB of weights into git:

* ``raven setup --free --experimental --yes`` -> Ollama itself, the weights and the three config files;
* ``raven models enable-heretic`` / the Admin screen -> :func:`enable` — preflight, pull, write
  ``DEFAULT_MODEL`` into the env file :class:`~raven.core.config.Settings` obeys;
* ``raven start`` -> :func:`ensure_heretic_model` with ``pull=False``, a presence check only;
* docker compose -> the ``heretic-init`` service pulls ``HERETIC_REF`` over Ollama's HTTP API;
* air-gapped -> ``ollama create -f models/Modelfile.heretic`` registers the hand-copied GGUF as
  ``deepseek-v4-heretic``, and the switch writes whichever of the two names ``/api/tags`` answers.

License of the weights chain (Qwen -> Jackrong -> xtools-at -> mradermacher GGUF) is apache-2.0.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from raven.core.hardware import Hardware, detect

HERETIC_OLLAMA_NAME = "deepseek-v4-heretic"
HERETIC_BUNDLED_REF = "hf.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF:Q4_K_M"
HERETIC_HF_REF = os.environ.get("HERETIC_REF", HERETIC_BUNDLED_REF)
HERETIC_RAVEN_MODEL = os.environ.get("HERETIC_MODEL", f"ollama/{HERETIC_HF_REF}")
HERETIC_GGUF_REPO = "mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF"
HERETIC_QUANT = "Q4_K_M"
# `GET https://huggingface.co/api/models/<HERETIC_GGUF_REPO>?blobs=true`, Q4_K_M sibling, 2026-11-10.
HERETIC_SIZE_GB = 5.63

_MIN_DISK_GB = 8.0
_MIN_TOTAL_RAM_GB = 8.0
_MIN_FREE_RAM_GB = 6.0
_GPU_OFFLOAD_MB = 8000
# The value DEFAULT_MODEL had before the experimental model was switched on. Nothing else writes it;
# `disable` restores from it and removes it.
_PREVIOUS_DEFAULT_KEY = "HERETIC_PREVIOUS_DEFAULT_MODEL"
_TIER_FIELDS = {
    "DEFAULT_MODEL": "default_model",
    "MODEL_FAST": "model_fast",
    "MODEL_BALANCED": "model_balanced",
    "MODEL_QUALITY": "model_quality",
}


@dataclass
class EnsureResult:
    ok: bool
    detail: str
    model: str = HERETIC_HF_REF


@dataclass
class SwitchResult:
    ok: bool
    detail: str
    env_file: Path | None = None
    previous: str | None = None
    pulled: bool = False
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ModelStatus:
    ref: str
    raven_model: str
    size_gb: float
    ollama_reachable: bool
    present: bool
    is_default: bool
    default_model: str
    hardware: Hardware
    blockers: list[str]
    env_file: Path
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "model": self.raven_model,
            "size_gb": self.size_gb,
            "ollama_reachable": self.ollama_reachable,
            "present": self.present,
            "is_default": self.is_default,
            "default_model": self.default_model,
            "env_file": str(self.env_file),
            "hardware": {
                "ram_total_gb": self.hardware.ram_total_gb,
                "ram_free_gb": self.hardware.ram_free_gb,
                "disk_free_gb": self.hardware.disk_free_gb,
                "vram_mb": self.hardware.vram_mb,
            },
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def preflight(hw: Hardware | None = None) -> list[str]:
    """What stands between this machine and a usable run, stated in numbers. Empty means go.

    The weights have to be resident to answer in reasonable time, so free RAM is checked as well as
    total: an 8 GB box that is already full will page a 5.63 GB model to disk on every token.
    """
    read = hw or detect()
    blockers: list[str] = []
    if read.disk_free_gb < _MIN_DISK_GB:
        blockers.append(
            f"{read.disk_free_gb:.1f} GB free on the model volume, needs {_MIN_DISK_GB:.0f} "
            f"GB for {HERETIC_SIZE_GB:.2f} GB of weights"
        )
    if read.ram_total_gb and read.ram_total_gb < _MIN_TOTAL_RAM_GB:
        blockers.append(f"{read.ram_total_gb:.1f} GB of RAM, needs {_MIN_TOTAL_RAM_GB:.0f} GB to hold a 9B at Q4_K_M")
    if read.vram_mb < _GPU_OFFLOAD_MB and read.ram_free_gb and read.ram_free_gb < _MIN_FREE_RAM_GB:
        blockers.append(
            f"{read.ram_free_gb:.1f} GB RAM free with {read.vram_mb} MB of VRAM to offload to, "
            f"needs {_MIN_FREE_RAM_GB:.1f} GB free"
        )
    return blockers


def reference_note() -> str | None:
    """Say when the size and the preflight no longer describe what will actually be downloaded.

    ``HERETIC_REF`` exists for a mirror of the same file, which keeps both numbers true. Pointing it at
    a different model is the operator's call, but the 5.63 GB label and the RAM thresholds below were
    measured for the bundled Q4_K_M and must not be read as a promise about that other file.
    """
    if HERETIC_HF_REF.rsplit("/", 1)[-1] == HERETIC_BUNDLED_REF.rsplit("/", 1)[-1]:
        return None
    return (
        f"HERETIC_REF is overridden to {HERETIC_HF_REF}; the {HERETIC_SIZE_GB:.2f} GB figure and the "
        "hardware preflight describe the bundled Q4_K_M, not that reference"
    )


def remote_tiers() -> dict[str, str]:
    """Model tiers other than the default that still point at a paid provider.

    Enabling one tier does not make the deployment free: a call that routes through ``MODEL_FAST``
    keeps spending credit, so the switch has to say which names are still remote. ``DEFAULT_MODEL`` is
    left out because switching this model is precisely what changes it. Read from ``Settings``, not
    ``os.environ``: a name set only in an env file never reaches the process env.
    """
    from raven.core.config import settings

    remote: dict[str, str] = {}
    for env_name, attr in _TIER_FIELDS.items():
        if env_name == "DEFAULT_MODEL":
            continue
        value = str(getattr(settings, attr, "") or "")
        if value and not value.startswith(("ollama/", "vllm/")):
            remote[env_name] = value
    return remote


def list_ollama_models(base_url: str, timeout: float = 5.0) -> list[str]:
    import httpx

    resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    names: list[str] = []
    for m in data.get("models", []):
        name = m.get("name", "")
        if name:
            names.append(name)
        model = m.get("model", "")
        if model and model not in names:
            names.append(model)
    return names


def _is_heretic(name: str) -> bool:
    return name in (HERETIC_OLLAMA_NAME, HERETIC_HF_REF) or HERETIC_GGUF_REPO.lower() in name.lower()


def _found_reference(names: list[str]) -> str:
    """The name Ollama answers the bundled weights under, preferring the canonical reference.

    Two routes put the same weights in front of the runtime: ``pull hf.co/…`` registers the reference,
    while ``ollama create -f models/Modelfile.heretic`` — the air-gapped import of a hand-copied GGUF —
    registers ``deepseek-v4-heretic``. A model string has to name the one the runtime actually has.
    """
    matched = [name for name in names if _is_heretic(name)]
    if not matched:
        return HERETIC_HF_REF
    return HERETIC_HF_REF if HERETIC_HF_REF in matched else sorted(matched)[0]


def _raven_model_for(reference: str) -> str:
    return HERETIC_RAVEN_MODEL if reference == HERETIC_HF_REF else f"ollama/{reference}"


def is_bundled_model(value: str) -> bool:
    """Whether a Raven model string calls the bundled weights, whichever name they landed under."""
    return value == HERETIC_RAVEN_MODEL or _is_heretic(value.removeprefix("ollama/"))


def _pull_via_api(base_url: str, ref: str, timeout: float = 1800.0) -> bool:
    import httpx

    resp = httpx.post(
        f"{base_url.rstrip('/')}/api/pull",
        json={"model": ref, "stream": False},
        timeout=timeout,
    )
    resp.raise_for_status()
    return True


def _pull_via_binary(ref: str, timeout: int = 1800) -> bool:
    ollama = shutil.which("ollama")
    if not ollama:
        return False
    result = subprocess.run(
        [ollama, "pull", ref],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return result.returncode == 0


def ensure_heretic_model(base_url: str, timeout: float = 5.0, pull: bool = True, force: bool = False) -> EnsureResult:
    """Ensure the bundled heretic model is present in Ollama, pulling it if needed.

    With ``pull=False`` only checks presence (fast, safe for ``raven start``).
    With ``pull=True`` downloads :data:`HERETIC_SIZE_GB` on first run (explicit command / compose init),
    and refuses when :func:`preflight` says the box cannot run it — unless ``force``.
    Never raises on pull failure: the caller must stay bootable and surface detail instead.
    """
    try:
        names = list_ollama_models(base_url, timeout=timeout)
    except Exception as exc:
        return EnsureResult(ok=False, detail=f"Ollama not reachable at {base_url}: {exc}")
    if any(_is_heretic(n) for n in names):
        return EnsureResult(ok=True, detail="already present", model=_found_reference(names))
    if not pull:
        return EnsureResult(
            ok=False,
            detail=f"missing, run: raven models enable-heretic ({HERETIC_HF_REF})",
        )
    blockers = preflight()
    if blockers and not force:
        return EnsureResult(
            ok=False,
            detail="host cannot run this model: " + "; ".join(blockers) + " (override with --force)",
        )
    try:
        if _pull_via_api(base_url, HERETIC_HF_REF):
            return EnsureResult(ok=True, detail=f"pulled {HERETIC_HF_REF} via api")
    except Exception as exc:
        api_err = str(exc)
    else:
        api_err = ""
    try:
        if _pull_via_binary(HERETIC_HF_REF):
            return EnsureResult(ok=True, detail=f"pulled {HERETIC_HF_REF} via ollama binary")
    except Exception as exc:
        return EnsureResult(ok=False, detail=f"pull failed: api={api_err} binary={exc}")
    detail = f"pull failed: api={api_err}" if api_err else "pull failed (no ollama binary)"
    return EnsureResult(ok=False, detail=detail)


def status(base_url: str, timeout: float = 3.0) -> ModelStatus:
    """The whole experimental-model picture, for the CLI, the screen and `raven doctor`."""
    from raven.core.config import effective_env_file, overshadowing_env_value, settings

    read = detect()
    blockers = preflight(read)
    try:
        names = list_ollama_models(base_url, timeout=timeout)
        reachable, present = True, any(_is_heretic(n) for n in names)
        reference = _found_reference(names) if present else HERETIC_HF_REF
    except Exception:
        reachable, present, reference = False, False, HERETIC_HF_REF
    warnings: list[str] = []
    note = reference_note()
    if note:
        warnings.append(note)
    if reachable and not present:
        warnings.append(f"not pulled ({HERETIC_SIZE_GB:.2f} GB, run: raven models enable-heretic)")
    shadow = overshadowing_env_value("DEFAULT_MODEL")
    if shadow is not None and not is_bundled_model(shadow):
        env = effective_env_file()
        warnings.append(
            f"DEFAULT_MODEL={shadow} is exported outside the env files and beats {env} at next start — "
            "clear it there or the switch will not hold"
        )
    remote = remote_tiers()
    for name, value in remote.items():
        warnings.append(f"{name}={value} still bills a hosted provider")
    return ModelStatus(
        ref=HERETIC_HF_REF,
        raven_model=_raven_model_for(reference),
        size_gb=HERETIC_SIZE_GB,
        ollama_reachable=reachable,
        present=present,
        is_default=is_bundled_model(settings.default_model),
        default_model=settings.default_model,
        hardware=read,
        blockers=blockers,
        env_file=effective_env_file(),
        warnings=warnings,
    )


def enable(base_url: str, *, pull: bool = True, force: bool = False, timeout: float = 5.0) -> SwitchResult:
    """Make the bundled model the one Raven calls, or say in numbers why it will not run."""
    from raven.core.config import (
        effective_env_file,
        overshadowing_env_value,
        read_env_value,
        refresh_settings_from_env,
        settings,
        write_env_value,
    )

    # Read before the write: setting the switch also updates this process's environment, after which
    # the two agree and the shadow can no longer be told apart from the value just written.
    shadow = overshadowing_env_value("DEFAULT_MODEL")
    result = ensure_heretic_model(base_url, timeout=timeout, pull=pull, force=force)
    if not result.ok:
        return SwitchResult(ok=False, detail=result.detail, blockers=preflight())

    path = effective_env_file()
    target = _raven_model_for(result.model)
    current = read_env_value("DEFAULT_MODEL", path) or settings.default_model
    original = read_env_value(_PREVIOUS_DEFAULT_KEY, path)
    if not original and current and current != target:
        original = current
    if original:
        write_env_value(_PREVIOUS_DEFAULT_KEY, original, path)
    write_env_value("DEFAULT_MODEL", target, path)
    refresh_settings_from_env()

    warnings: list[str] = []
    note = reference_note()
    if note:
        warnings.append(note)
    if shadow is not None and not is_bundled_model(shadow):
        warnings.append(
            f"DEFAULT_MODEL={shadow} is exported outside the env files and beats {path} at next start — "
            "clear it there or the switch will not hold"
        )
    remote = remote_tiers()
    if remote:
        warnings.append("still hosted: " + ", ".join(f"{k}={v}" for k, v in remote.items()))
    return SwitchResult(
        ok=True,
        detail=f"DEFAULT_MODEL={target}" + (f" (was {original})" if original else ""),
        env_file=path,
        previous=original,
        pulled=result.detail.startswith("pulled"),
        warnings=warnings,
    )


def disable() -> SwitchResult:
    """Put back the model that was configured before the bundled one was switched on."""
    from raven.core.config import (
        drop_env_value,
        effective_env_file,
        read_env_value,
        refresh_settings_from_env,
        write_env_value,
    )

    path = effective_env_file()
    previous = read_env_value(_PREVIOUS_DEFAULT_KEY, path)
    if not previous:
        return SwitchResult(
            ok=False,
            detail=f"nothing to restore: no {_PREVIOUS_DEFAULT_KEY} in {path}",
            env_file=path,
        )
    drop_env_value(_PREVIOUS_DEFAULT_KEY, path)
    write_env_value("DEFAULT_MODEL", previous, path)
    refresh_settings_from_env()
    return SwitchResult(ok=True, detail=f"DEFAULT_MODEL={previous}", env_file=path, previous=previous)
