"""The bundled free experimental model: the numbers it refuses on, the pull, and the switch.

The switch is the point of the whole module, so these tests drive the real env-file cascade in
``raven.core.config`` — a mock here would prove the wiring exists without proving it bites.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from raven.core import config, heretic_model
from raven.core.hardware import Hardware
from raven.core.heretic_model import (
    _PREVIOUS_DEFAULT_KEY,
    HERETIC_GGUF_REPO,
    HERETIC_HF_REF,
    HERETIC_OLLAMA_NAME,
    HERETIC_RAVEN_MODEL,
    HERETIC_SIZE_GB,
    disable,
    enable,
    ensure_heretic_model,
    preflight,
    remote_tiers,
    status,
)

_SWITCHED_NAMES = (
    "DEFAULT_MODEL",
    "MODEL_FAST",
    "MODEL_BALANCED",
    "MODEL_QUALITY",
    "OLLAMA_BASE_URL",
    _PREVIOUS_DEFAULT_KEY,
)


@pytest.fixture(autouse=True)
def env_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pin_env_names: Callable[[Iterable[str]], None]
) -> Iterator[SimpleNamespace]:
    """The real cascade pointed at three files in tmp, and the switchable env names cleared.

    ``write_env_value`` also sets ``os.environ``, so anything this module writes has to be undone or the
    next test in the batch reads the switch — and clearing means the absent-aware pin, because
    ``monkeypatch.delenv(name, raising=False)`` records nothing for a name the machine does not have. The
    names are cleared rather than recorded because a value inherited from the machine would decide which
    branch of the precedence rules a test exercises.
    """
    root_env = tmp_path / "install.env"
    user_env = tmp_path / "home" / ".raven.env"
    local_env = tmp_path / ".env"
    user_env.parent.mkdir()
    monkeypatch.setattr(config, "_ENV_FILE_CANDIDATES", [str(root_env), str(user_env), str(local_env)])
    monkeypatch.setattr(config, "_USER_ENV_FILE", user_env)
    pin_env_names(_SWITCHED_NAMES)
    for attr in ("default_model", "model_fast", "model_balanced", "model_quality"):
        monkeypatch.setattr(config.settings, attr, str(getattr(config.settings, attr) or ""))
    yield SimpleNamespace(root=root_env, user=user_env, local=local_env, tmp=tmp_path)


def _present(model: str = HERETIC_HF_REF) -> None:
    """Pretend Ollama already holds the weights, so the switch is tested without a 5.63 GB pull."""
    heretic_model.list_ollama_models = lambda *_a, **_k: [model]


@pytest.fixture
def restore_ollama_probe() -> object:
    original = heretic_model.list_ollama_models
    yield
    heretic_model.list_ollama_models = original


class TestPreflight:
    def test_a_box_that_can_hold_the_weights_is_told_so(self) -> None:
        assert preflight(Hardware(ram_total_gb=32.0, ram_free_gb=24.0, disk_free_gb=200.0, vram_mb=24576)) == []

    def test_low_disk_states_the_measured_and_required_gigabytes(self) -> None:
        blocked = preflight(Hardware(ram_total_gb=32.0, ram_free_gb=24.0, disk_free_gb=5.0, vram_mb=24576))
        assert len(blocked) == 1
        assert "5.0 GB free" in blocked[0] and "8 GB" in blocked[0] and f"{HERETIC_SIZE_GB:.2f} GB" in blocked[0]

    def test_too_little_ram_total(self) -> None:
        blocked = preflight(Hardware(ram_total_gb=4.0, ram_free_gb=3.0, disk_free_gb=100.0, vram_mb=0))
        assert any("4.0 GB of RAM" in b for b in blocked)

    def test_cpu_only_box_needs_the_weights_resident_in_free_ram(self) -> None:
        blocked = preflight(Hardware(ram_total_gb=8.4, ram_free_gb=0.9, disk_free_gb=59.0, vram_mb=0))
        assert any("0.9 GB RAM free" in b for b in blocked)

    def test_a_gpu_can_carry_what_ram_cannot(self) -> None:
        assert preflight(Hardware(ram_total_gb=16.0, ram_free_gb=1.0, disk_free_gb=100.0, vram_mb=12288)) == []

    def test_a_memory_probe_that_answered_zero_is_not_read_as_no_ram(self) -> None:
        """A broken probe must not fabricate a RAM blocker; it would look like a small machine."""
        blocked = preflight(Hardware(ram_total_gb=0.0, ram_free_gb=0.0, disk_free_gb=100.0, vram_mb=0))
        assert blocked == []


class TestReferenceMatching:
    def test_ships_as_the_short_name_the_full_ref_or_any_quant_of_the_repo(self) -> None:
        for name in (
            HERETIC_OLLAMA_NAME,
            HERETIC_HF_REF,
            f"hf.co/{HERETIC_GGUF_REPO.lower()}:q4_k_m",
            f"{HERETIC_GGUF_REPO}:Q8_0",
        ):
            assert heretic_model._is_heretic(name) is True, name

    def test_other_models_are_not_the_bundled_one(self) -> None:
        for name in ("llama3", "qwen2.5:7b", "ollama/qwen2.5", ""):
            assert heretic_model._is_heretic(name) is False, name


class TestBundledModelNames:
    """Two routes put the same weights in front of Ollama; every surface must agree which one is in use."""

    def test_the_canonical_reference_wins_when_both_names_are_registered(self) -> None:
        names = [HERETIC_OLLAMA_NAME, "llama3", HERETIC_HF_REF]
        assert heretic_model._found_reference(names) == HERETIC_HF_REF

    def test_an_imported_gguf_is_named_by_the_alias_it_was_created_under(self) -> None:
        assert heretic_model._found_reference(["llama3", HERETIC_OLLAMA_NAME]) == HERETIC_OLLAMA_NAME

    def test_the_answer_does_not_depend_on_the_order_ollama_lists_models_in(self) -> None:
        other = f"{HERETIC_GGUF_REPO}:Q8_0"
        assert heretic_model._found_reference([HERETIC_OLLAMA_NAME, other]) == heretic_model._found_reference(
            [other, HERETIC_OLLAMA_NAME]
        )

    def test_no_match_falls_back_to_the_reference_a_pull_would_use(self) -> None:
        assert heretic_model._found_reference(["llama3"]) == HERETIC_HF_REF

    def test_the_model_string_names_what_the_runtime_answers_to(self) -> None:
        assert heretic_model._raven_model_for(HERETIC_HF_REF) == HERETIC_RAVEN_MODEL
        assert heretic_model._raven_model_for(HERETIC_OLLAMA_NAME) == f"ollama/{HERETIC_OLLAMA_NAME}"

    def test_one_predicate_decides_for_start_doctor_and_the_screen(self) -> None:
        for value in (HERETIC_RAVEN_MODEL, f"ollama/{HERETIC_OLLAMA_NAME}", f"ollama/{HERETIC_HF_REF}"):
            assert heretic_model.is_bundled_model(value) is True, value
        for value in ("", "groq/openai/gpt-oss-120b", "ollama/llama3", "ollama/hf.co/someone/other-GGUF:Q4_K_M"):
            assert heretic_model.is_bundled_model(value) is False, value


class TestAirGappedImport:
    """`ollama create -f models/Modelfile.heretic` registers an alias, not the hf.co reference."""

    def test_the_switch_writes_the_alias_when_that_is_the_only_name_ollama_has(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _present(HERETIC_OLLAMA_NAME)
        env_files.local.write_text("DEFAULT_MODEL=groq/openai/gpt-oss-120b\n", encoding="utf-8")
        monkeypatch.setattr(config.settings, "default_model", "groq/openai/gpt-oss-120b")

        result = enable("http://x", pull=False)

        assert result.ok is True, result.detail
        assert config.read_env_value("DEFAULT_MODEL", env_files.local) == f"ollama/{HERETIC_OLLAMA_NAME}"
        assert config.settings.default_model == f"ollama/{HERETIC_OLLAMA_NAME}"
        assert result.previous == "groq/openai/gpt-oss-120b"
        assert f"DEFAULT_MODEL=ollama/{HERETIC_OLLAMA_NAME}" in result.detail

    def test_the_screen_and_doctor_call_the_alias_in_use(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _present(HERETIC_OLLAMA_NAME)
        monkeypatch.setattr(config.settings, "default_model", f"ollama/{HERETIC_OLLAMA_NAME}")

        st = status("http://x")

        assert st.present is True and st.is_default is True
        assert st.raven_model == f"ollama/{HERETIC_OLLAMA_NAME}"
        assert st.to_dict()["model"] == f"ollama/{HERETIC_OLLAMA_NAME}"
        assert st.ref == HERETIC_HF_REF, "the pull reference stays canonical"

    def test_re_enabling_an_alias_switch_does_not_bookmark_the_alias_as_the_previous_model(
        self, env_files: SimpleNamespace, restore_ollama_probe: object
    ) -> None:
        _present(HERETIC_OLLAMA_NAME)
        env_files.local.write_text("DEFAULT_MODEL=groq/openai/gpt-oss-120b\n", encoding="utf-8")
        enable("http://x", pull=False)
        second = enable("http://x", pull=False)
        assert second.previous == "groq/openai/gpt-oss-120b"
        assert disable().detail == "DEFAULT_MODEL=groq/openai/gpt-oss-120b"

    def test_the_modelfile_creates_the_name_the_switch_looks_for(self) -> None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "models" / "Modelfile.heretic").read_text(encoding="utf-8")
        assert f"ollama create {HERETIC_OLLAMA_NAME} -f models/Modelfile.heretic" in text
        assert f"DEFAULT_MODEL=ollama/{HERETIC_OLLAMA_NAME}" in text
        from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
        assert len(from_lines) == 1 and from_lines[0].endswith(".gguf")
        assert not any(line.startswith("TEMPLATE") for line in text.splitlines()), "GGUF metadata owns the template"
        assert f"{HERETIC_SIZE_GB:.2f} GB" in text

    def test_the_modelfile_documents_commands_that_exist(self) -> None:
        from raven.cli import models_cmd, setup_cmd

        root = Path(__file__).resolve().parents[2]
        text = (root / "models" / "Modelfile.heretic").read_text(encoding="utf-8")
        assert "raven models enable-heretic --no-pull" in text
        assert "enable-heretic" in models_cmd.models_group.commands
        assert {"--free", "--experimental", "--yes"} <= {
            option for param in setup_cmd.setup.params for option in param.opts
        }


class TestReferenceOverride:
    """HERETIC_REF is for a mirror of the same file; a different model must not inherit its numbers."""

    def test_a_mirror_of_the_same_file_keeps_the_size_and_the_preflight_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mirror = "https://weights.internal/" + HERETIC_HF_REF.rsplit("/", 1)[-1]
        monkeypatch.setattr(heretic_model, "HERETIC_HF_REF", mirror)
        assert heretic_model.reference_note() is None

    def test_a_different_model_is_not_described_by_the_bundled_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        other = "hf.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-4B-UNCENSORED-heretic-GGUF:Q4_K_M"
        monkeypatch.setattr(heretic_model, "HERETIC_HF_REF", other)
        note = heretic_model.reference_note()
        assert note is not None
        assert other in note and f"{HERETIC_SIZE_GB:.2f} GB" in note and "preflight" in note

    def test_the_note_reaches_the_screen_and_the_switch(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        other = "hf.co/mirror/another-model-GGUF:Q4_K_M"
        monkeypatch.setattr(heretic_model, "HERETIC_HF_REF", other)
        monkeypatch.setattr(heretic_model, "HERETIC_RAVEN_MODEL", f"ollama/{other}")
        _present(other)
        assert any("overridden" in w for w in status("http://x").warnings)
        assert any("overridden" in w for w in enable("http://x", pull=False).warnings)


class TestThePageMatchesTheCode:
    """docs/local-models.md is the page a new operator follows; its numbers may not drift from the code."""

    @pytest.fixture
    def page(self) -> str:
        root = Path(__file__).resolve().parents[2]
        return (root / "docs" / "local-models.md").read_text(encoding="utf-8")

    def test_the_reference_the_size_and_the_thresholds_are_the_shipped_ones(self, page: str) -> None:
        from raven.core.heretic_model import _GPU_OFFLOAD_MB, _MIN_DISK_GB, _MIN_FREE_RAM_GB, _MIN_TOTAL_RAM_GB

        assert HERETIC_HF_REF in page
        assert f"{HERETIC_SIZE_GB:.2f} GB" in page
        assert f"| {_MIN_DISK_GB:.0f} GB |" in page
        assert f"| {_MIN_TOTAL_RAM_GB:.0f} GB |" in page
        assert f"| {_MIN_FREE_RAM_GB:.0f} GB |" in page
        assert f"{_GPU_OFFLOAD_MB} MB" in page

    def test_every_command_the_page_tells_you_to_run_exists(self, page: str) -> None:
        from raven.cli import models_cmd
        from raven.cli.main import cli

        for command in ("setup", "start", "models", "doctor", "repl"):
            assert f"raven {command}" in page, command
            assert command in cli.commands, command
        for sub in ("list", "enable-heretic", "disable-heretic"):
            assert f"raven models {sub}" in page, sub
            assert sub in models_cmd.models_group.commands, sub
        assert "--no-pull" in page and "--force" in page and "--yes" in page

    def test_the_api_path_is_the_one_the_server_serves_and_the_screen_calls(self, page: str) -> None:
        root = Path(__file__).resolve().parents[2]
        path = "/api/admin/models/experimental"
        assert path in page
        assert path in (root / "web" / "src" / "pages" / "Admin.tsx").read_text(encoding="utf-8")
        admin = (root / "raven" / "core" / "admin_api.py").read_text(encoding="utf-8")
        assert 'prefix="/api/admin"' in admin and '@router.get("/models/experimental")' in admin

    def test_the_air_gapped_commands_are_the_ones_the_modelfile_prints(self, page: str) -> None:
        root = Path(__file__).resolve().parents[2]
        modelfile = (root / "models" / "Modelfile.heretic").read_text(encoding="utf-8")
        assert f"ollama create {HERETIC_OLLAMA_NAME} -f models/Modelfile.heretic" in page
        assert f"ollama create {HERETIC_OLLAMA_NAME} -f models/Modelfile.heretic" in modelfile
        assert "raven models enable-heretic --no-pull" in page

    def test_no_shipped_file_repeats_the_retired_lazy_pull_claim(self) -> None:
        """`raven start` never downloads, and the size is the measured one — not an earlier rounding.

        Both claims were retired by this wave, and they had already crept back into the ignore files,
        which no prose page is checked against.
        """
        root = Path(__file__).resolve().parents[2]
        for rel in (".gitignore", ".dockerignore", ".env.example", "models/Modelfile.heretic"):
            text = (root / rel).read_text(encoding="utf-8")
            assert "lazy" not in text.lower(), rel
            for figure in re.findall(r"(\d+(?:\.\d+)?)\s*GB", text):
                assert abs(float(figure) - HERETIC_SIZE_GB) < 0.005, (rel, figure)


class TestOllamaCalls:
    def test_tags_url_is_built_from_the_base_without_a_trailing_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        seen: dict[str, object] = {}

        def _get(url: str, **kwargs: object) -> SimpleNamespace:
            seen["url"] = url
            seen["kwargs"] = kwargs
            return SimpleNamespace(
                json=lambda: {"models": [{"name": "llama3", "model": "llama3:latest"}, {"name": HERETIC_OLLAMA_NAME}]},
                raise_for_status=lambda: None,
            )

        monkeypatch.setattr(httpx, "get", _get)
        names = heretic_model.list_ollama_models("http://127.0.0.1:11434/")
        assert seen["url"] == "http://127.0.0.1:11434/api/tags"
        assert names == ["llama3", "llama3:latest", HERETIC_OLLAMA_NAME]

    def test_pull_asks_ollama_for_the_reference_without_streaming(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        seen: dict[str, object] = {}

        def _post(url: str, **kwargs: object) -> SimpleNamespace:
            seen["url"] = url
            seen["json"] = kwargs.get("json")
            return SimpleNamespace(raise_for_status=lambda: None)

        monkeypatch.setattr(httpx, "post", _post)
        assert heretic_model._pull_via_api("http://localhost:11434", HERETIC_HF_REF) is True
        assert seen["url"] == "http://localhost:11434/api/pull"
        assert seen["json"] == {"model": HERETIC_HF_REF, "stream": False}

    def test_binary_pull_is_an_argv_list_and_needs_the_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[object] = []
        monkeypatch.setattr(shutil, "which", lambda _exe: None)
        assert heretic_model._pull_via_binary(HERETIC_HF_REF) is False

        monkeypatch.setattr(shutil, "which", lambda _exe: "C:/ollama.exe")

        def _record(cmd: list[str], **_k: object) -> SimpleNamespace:
            calls.append(cmd)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(subprocess, "run", _record)
        assert heretic_model._pull_via_binary(HERETIC_HF_REF) is True
        assert calls == [["C:/ollama.exe", "pull", HERETIC_HF_REF]]

    def test_binary_pull_failure_is_reported_not_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda _exe: "C:/ollama.exe")
        monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=1))
        assert heretic_model._pull_via_binary(HERETIC_HF_REF) is False


class TestEnsure:
    def test_unreachable_ollama_names_the_address_it_tried(
        self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _refuse(*_a: object, **_k: object) -> list[str]:
            raise ConnectionError("connection refused")

        monkeypatch.setattr(heretic_model, "list_ollama_models", _refuse)
        res = ensure_heretic_model("http://127.0.0.1:11434")
        assert res.ok is False
        assert "http://127.0.0.1:11434" in res.detail and "connection refused" in res.detail

    def test_present_weights_are_not_pulled_again(
        self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _present()
        monkeypatch.setattr(heretic_model, "_pull_via_api", lambda *_a, **_k: pytest.fail("re-pulled"))
        assert ensure_heretic_model("http://x").detail == "already present"

    def test_startup_check_never_downloads(self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: ["llama3"])
        res = ensure_heretic_model("http://x", pull=False)
        assert res.ok is False
        assert "raven models enable-heretic" in res.detail and HERETIC_HF_REF in res.detail

    def test_a_refusing_preflight_blocks_the_download_and_names_the_override(
        self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "preflight", lambda *_a, **_k: ["0.9 GB RAM free"])
        monkeypatch.setattr(heretic_model, "_pull_via_api", lambda *_a, **_k: pytest.fail("pulled anyway"))
        res = ensure_heretic_model("http://x")
        assert res.ok is False and "--force" in res.detail and "0.9 GB RAM free" in res.detail

    def test_force_pulls_over_a_refusing_preflight(
        self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "preflight", lambda *_a, **_k: ["0.9 GB RAM free"])
        monkeypatch.setattr(heretic_model, "_pull_via_api", lambda *_a, **_k: True)
        assert ensure_heretic_model("http://x", force=True).detail.startswith("pulled")

    def test_the_binary_is_the_fallback_when_the_api_refuses(
        self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("403 pull forbidden")

        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "preflight", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "_pull_via_api", _boom)
        monkeypatch.setattr(heretic_model, "_pull_via_binary", lambda *_a, **_k: True)
        res = ensure_heretic_model("http://x")
        assert res.ok is True and "via ollama binary" in res.detail

    def test_both_pull_paths_failing_are_both_reported(
        self, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> bool:
            raise RuntimeError("api down")

        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "preflight", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "_pull_via_api", _boom)
        monkeypatch.setattr(heretic_model, "_pull_via_binary", lambda *_a, **_k: False)
        res = ensure_heretic_model("http://x")
        assert res.ok is False and "api=api down" in res.detail


class TestRemoteTiers:
    def test_local_tiers_are_not_billed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "default_model", HERETIC_RAVEN_MODEL)
        monkeypatch.setattr(config.settings, "model_fast", "ollama/llama3")
        monkeypatch.setattr(config.settings, "model_balanced", "vllm/qwen")
        monkeypatch.setattr(config.settings, "model_quality", "")
        assert remote_tiers() == {}

    def test_a_hosted_tier_is_named_with_its_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "model_fast", "groq/openai/gpt-oss-120b")
        assert remote_tiers() == {"MODEL_FAST": "groq/openai/gpt-oss-120b"}

    def test_the_tier_the_switch_owns_is_never_reported_as_remote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "default_model", "groq/openai/gpt-oss-120b")
        assert "DEFAULT_MODEL" not in remote_tiers()


class TestSwitch:
    def test_enable_writes_the_file_the_app_reads_and_remembers_the_previous_model(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _present()
        env_files.local.write_text("DEFAULT_MODEL=groq/openai/gpt-oss-120b\nOPENAI_API_KEY=keepme\n", encoding="utf-8")
        monkeypatch.setattr(config.settings, "default_model", "groq/openai/gpt-oss-120b")

        result = enable("http://x", pull=False)

        assert result.ok is True, result.detail
        text = env_files.local.read_text(encoding="utf-8")
        assert f"DEFAULT_MODEL={HERETIC_RAVEN_MODEL}" in text
        assert f"{_PREVIOUS_DEFAULT_KEY}=groq/openai/gpt-oss-120b" in text
        assert "OPENAI_API_KEY=keepme" in text, "the file carries API keys; nothing else may be rewritten"
        assert result.previous == "groq/openai/gpt-oss-120b"
        assert config.settings.default_model == HERETIC_RAVEN_MODEL, "the live process must stop using the old model"

    def test_the_written_switch_survives_a_fresh_process(
        self, env_files: SimpleNamespace, restore_ollama_probe: object
    ) -> None:
        """What the operator sees: the next `raven start` reads the value the switch wrote."""
        _present()
        env_files.local.write_text("DEFAULT_MODEL=groq/openai/gpt-oss-120b\n", encoding="utf-8")
        assert enable("http://x", pull=False).ok is True
        env = {k: v for k, v in os.environ.items() if k != "DEFAULT_MODEL"}
        run = subprocess.run(
            [sys.executable, "-c", "import raven.core.config as c; print(c.settings.default_model)"],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(env_files.tmp),
            timeout=180,
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout.strip().endswith(HERETIC_RAVEN_MODEL)

    def test_enabling_twice_does_not_record_the_switch_as_the_previous_model(
        self, env_files: SimpleNamespace, restore_ollama_probe: object
    ) -> None:
        _present()
        env_files.local.write_text("DEFAULT_MODEL=groq/openai/gpt-oss-120b\n", encoding="utf-8")
        enable("http://x", pull=False)
        second = enable("http://x", pull=False)
        assert second.previous == "groq/openai/gpt-oss-120b"
        assert config.read_env_value(_PREVIOUS_DEFAULT_KEY, env_files.local) == "groq/openai/gpt-oss-120b"

    def test_disable_puts_the_original_model_back_and_forgets_it(
        self, env_files: SimpleNamespace, restore_ollama_probe: object
    ) -> None:
        _present()
        env_files.local.write_text("DEFAULT_MODEL=groq/openai/gpt-oss-120b\n", encoding="utf-8")
        enable("http://x", pull=False)

        result = disable()

        assert result.ok is True and result.detail == "DEFAULT_MODEL=groq/openai/gpt-oss-120b"
        text = env_files.local.read_text(encoding="utf-8")
        assert "DEFAULT_MODEL=groq/openai/gpt-oss-120b" in text
        assert _PREVIOUS_DEFAULT_KEY not in text, "a stale bookmark would restore the wrong model later"

    def test_disable_says_so_when_there_is_nothing_to_restore(self, env_files: SimpleNamespace) -> None:
        result = disable()
        assert result.ok is False and "nothing to restore" in result.detail

    def test_a_refusing_preflight_leaves_the_configuration_untouched(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [])
        monkeypatch.setattr(heretic_model, "preflight", lambda *_a, **_k: ["0.9 GB RAM free"])
        result = enable("http://x")
        assert result.ok is False and result.blockers == ["0.9 GB RAM free"]
        assert not env_files.local.exists() and not env_files.user.exists()
        assert "0.9 GB RAM free" in result.detail

    def test_the_switch_warns_about_tiers_that_still_bill_a_hosted_provider(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _present()
        monkeypatch.setattr(config.settings, "model_quality", "anthropic/claude-sonnet-4-5")
        result = enable("http://x", pull=False)
        assert any("MODEL_QUALITY=anthropic/claude-sonnet-4-5" in w for w in result.warnings)
        assert not any("DEFAULT_MODEL" in w for w in result.warnings)

    def test_the_switch_warns_when_the_environment_beats_the_file_it_wrote(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _present()
        monkeypatch.setenv("DEFAULT_MODEL", "groq/openai/gpt-oss-120b")
        result = enable("http://x", pull=False)
        assert any("outside the env files" in w and "groq/openai/gpt-oss-120b" in w for w in result.warnings)

    def test_written_values_keep_the_files_line_endings_and_order(
        self, env_files: SimpleNamespace, restore_ollama_probe: object
    ) -> None:
        _present()
        raw = "ANTHROPIC_API_KEY=secret\r\nDEFAULT_MODEL=openrouter/x\r\nLOG_LEVEL=info\r\n"
        env_files.local.write_bytes(raw.encode("utf-8"))
        enable("http://x", pull=False)
        after = env_files.local.read_bytes().decode("utf-8")
        assert after.count("\r\n") == after.count("\n"), "CRLF file must stay CRLF"
        assert after.splitlines()[0] == "ANTHROPIC_API_KEY=secret"


class TestStatus:
    def test_reports_every_number_the_screen_shows(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [HERETIC_HF_REF])
        monkeypatch.setattr(heretic_model, "detect", lambda: Hardware(16.0, 12.0, 100.0, 0))
        env_files.local.write_text(f"DEFAULT_MODEL={HERETIC_RAVEN_MODEL}\n", encoding="utf-8")
        monkeypatch.setattr(config.settings, "default_model", HERETIC_RAVEN_MODEL)

        payload = status("http://x").to_dict()

        assert payload["ref"] == HERETIC_HF_REF
        assert payload["model"] == HERETIC_RAVEN_MODEL
        assert payload["size_gb"] == HERETIC_SIZE_GB
        assert payload["ollama_reachable"] is True and payload["present"] is True and payload["is_default"] is True
        assert payload["hardware"] == {"ram_total_gb": 16.0, "ram_free_gb": 12.0, "disk_free_gb": 100.0, "vram_mb": 0}
        assert payload["blockers"] == [] and payload["warnings"] == []

    def test_an_unreachable_ollama_is_a_warning_not_a_crash(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _refuse(*_a: object, **_k: object) -> list[str]:
            raise ConnectionError("no ollama")

        monkeypatch.setattr(heretic_model, "list_ollama_models", _refuse)
        monkeypatch.setattr(heretic_model, "detect", lambda: Hardware(32.0, 24.0, 500.0, 24576))
        st = status("http://x")
        assert st.ollama_reachable is False and st.present is False and st.blockers == []

    def test_reachable_but_not_pulled_says_the_size_and_the_command(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: ["llama3"])
        monkeypatch.setattr(heretic_model, "detect", lambda: Hardware(32.0, 24.0, 500.0, 24576))
        st = status("http://x")
        assert any(f"{HERETIC_SIZE_GB:.2f} GB" in w and "raven models enable-heretic" in w for w in st.warnings)

    def test_a_live_process_environment_that_beats_the_file_is_named(
        self, env_files: SimpleNamespace, restore_ollama_probe: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEFAULT_MODEL", "hosted/model")
        monkeypatch.setattr(heretic_model, "list_ollama_models", lambda *_a, **_k: [HERETIC_OLLAMA_NAME])
        monkeypatch.setattr(heretic_model, "detect", lambda: Hardware(32.0, 24.0, 500.0, 24576))
        st = status("http://x")
        assert any("outside the env files" in w and "hosted/model" in w for w in st.warnings)


class TestEnvFilePlumbing:
    def test_the_highest_existing_file_wins_and_the_user_file_is_the_fallback(self, env_files: SimpleNamespace) -> None:
        assert config.effective_env_file() == env_files.user
        env_files.root.write_text("A=1\n", encoding="utf-8")
        assert config.effective_env_file() == env_files.root
        env_files.local.write_text("A=2\n", encoding="utf-8")
        assert config.effective_env_file() == env_files.local

    def test_the_written_switch_is_not_shadowed_by_a_lower_file(self, env_files: SimpleNamespace) -> None:
        """`env_file_candidates` ascending, so nothing above the effective file can outrank it."""
        env_files.root.write_text("DEFAULT_MODEL=root/model\n", encoding="utf-8")
        env_files.local.write_text("DEFAULT_MODEL=local/model\n", encoding="utf-8")
        assert config.overshadowing_env_value("DEFAULT_MODEL") is None

    def test_the_process_environment_is_the_shadow_that_reaches_the_next_process(
        self, env_files: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_files.local.write_text("DEFAULT_MODEL=file/model\n", encoding="utf-8")
        monkeypatch.setenv("DEFAULT_MODEL", "shell/model")
        assert config.overshadowing_env_value("DEFAULT_MODEL") == "shell/model"

        monkeypatch.setenv("DEFAULT_MODEL", "file/model")
        assert config.overshadowing_env_value("DEFAULT_MODEL") is None, "an env that agrees is not a shadow"

        monkeypatch.delenv("DEFAULT_MODEL")
        assert config.overshadowing_env_value("DEFAULT_MODEL") is None

    def test_the_precedence_claim_is_measured_not_assumed(self, env_files: SimpleNamespace) -> None:
        """Every guard in this file rests on dotenv-vs-environment order, so prove it in a real process."""
        env_files.local.write_text("DEFAULT_MODEL=file/model\n", encoding="utf-8")
        base = {k: v for k, v in os.environ.items() if k != "DEFAULT_MODEL"}

        def _resolve(extra: dict[str, str]) -> str:
            run = subprocess.run(
                [sys.executable, "-c", "import raven.core.config as c; print(c.settings.default_model)"],
                env=dict(base, **extra),
                capture_output=True,
                text=True,
                cwd=str(env_files.tmp),
                timeout=180,
            )
            assert run.returncode == 0, run.stderr
            return run.stdout.strip().splitlines()[-1]

        assert _resolve({}) == "file/model"
        assert _resolve({"DEFAULT_MODEL": "shell/model"}) == "shell/model"

    def test_write_keeps_every_other_line_and_reports_what_it_replaced(self, env_files: SimpleNamespace) -> None:
        env_files.local.write_text("X=1\nDEFAULT_MODEL=old\nY=2\nDEFAULT_MODEL=older\n", encoding="utf-8")
        assert config.write_env_value("DEFAULT_MODEL", "new", env_files.local) in ("old", "older")
        lines = env_files.local.read_text(encoding="utf-8").splitlines()
        assert lines == ["X=1", "DEFAULT_MODEL=new", "Y=2"], "duplicate assignments collapse into one"
        assert os.environ["DEFAULT_MODEL"] == "new"

    def test_comments_and_blank_lines_are_not_assignments(self, env_files: SimpleNamespace) -> None:
        env_files.local.write_text("# DEFAULT_MODEL=commented\n\nDEFAULT_MODEL=real\n", encoding="utf-8")
        assert config.read_env_value("DEFAULT_MODEL", env_files.local) == "real"

    def test_creating_an_env_file_does_not_leak_it_world_readable(self, env_files: SimpleNamespace) -> None:
        config.write_env_value("DEFAULT_MODEL", "x", env_files.user)
        assert env_files.user.is_file()
        if os.name != "nt":
            assert env_files.user.stat().st_mode & 0o077 == 0, "the file will hold API keys"

    def test_drop_removes_only_the_named_key(self, env_files: SimpleNamespace) -> None:
        env_files.local.write_text("KEEP=1\nDROP=2\n", encoding="utf-8")
        config.drop_env_value("DROP", env_files.local)
        assert env_files.local.read_text(encoding="utf-8").splitlines() == ["KEEP=1"]
        assert "DROP" not in os.environ

    def test_refresh_moves_the_live_settings_and_skips_an_empty_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.settings, "default_model", "before")
        monkeypatch.setenv("DEFAULT_MODEL", "after")
        changed = config.refresh_settings_from_env()
        assert "DEFAULT_MODEL" in changed
        assert config.settings.default_model == "after"

        monkeypatch.setenv("DEFAULT_MODEL", "   ")
        monkeypatch.setattr(config.settings, "default_model", "keep")
        assert "DEFAULT_MODEL" not in config.refresh_settings_from_env()
        assert config.settings.default_model == "keep"
