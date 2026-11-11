"""``raven setup --free`` is the first command a new operator runs, so the download guard lives here.

The whole point of the command is a stack that answers without an API key, which makes two things
worth pinning: every model string it writes must be an Ollama tag (a hosted name silently bills), and
the 5.63 GB ``--experimental`` weights must never start downloading — nor be configured without being
downloaded — unless the operator said yes. Everything runs through the real config and env writers in
a temporary directory; only the hardware reading, the Ollama binary, the installer and the pull are
stubbed, so no test here can move a byte on this machine.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml
from click.testing import CliRunner

from raven.cli import setup_cmd
from raven.core.artifacts.paths import ArtifactPaths
from raven.core.features import FeatureFlags, env_flag_names
from raven.core.hardware import Hardware
from raven.core.heretic_model import HERETIC_HF_REF, HERETIC_SIZE_GB

_REAL_PULL = setup_cmd._pull_model

# vram 12288 -> llama3.1:8b by tier, and preflight passes (disk, total RAM, GPU offload >= 8000 MB).
_GOOD_BOX = Hardware(ram_total_gb=24.0, ram_free_gb=18.0, disk_free_gb=500.0, vram_mb=12288)
# Fails on disk (4.0 < 8 GB) and on free RAM with no GPU to offload to (0.9 < 6.0 GB).
_SMALL_BOX = Hardware(ram_total_gb=16.0, ram_free_gb=0.9, disk_free_gb=4.0, vram_mb=0)

_WRITTEN_KEYS = (
    "DEFAULT_MODEL",
    "MODEL_FAST",
    "MODEL_BALANCED",
    "MODEL_QUALITY",
    "OLLAMA_BASE_URL",
    "WEB_SECRET_KEY",
)


@pytest.fixture(autouse=True)
def _no_machine_effects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    box: dict[str, Any] = {"hw": _GOOD_BOX, "pulls": []}
    for name in _WRITTEN_KEYS:
        monkeypatch.setenv(name, os.environ.get(name, ""))
    for env_var in env_flag_names().values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("COLUMNS", "300")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_cmd, "detect", lambda: box["hw"])
    monkeypatch.setattr(setup_cmd, "_find_ollama", lambda: "C:/fake/ollama.exe")
    monkeypatch.setattr(setup_cmd, "_install_ollama", lambda: pytest.fail("setup installed Ollama unasked"))
    monkeypatch.setattr(setup_cmd, "_ollama_serve", lambda: True)

    def _pull(model: str) -> bool:
        box["pulls"].append(model)
        return True

    monkeypatch.setattr(setup_cmd, "_pull_model", _pull)
    return box


@pytest.fixture
def pulls(_no_machine_effects: dict[str, Any]) -> list[str]:
    return cast(list[str], _no_machine_effects["pulls"])


@pytest.fixture
def box(_no_machine_effects: dict[str, Any]) -> dict[str, Any]:
    return _no_machine_effects


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """An operator at a terminal: CliRunner hands the command a pipe, so isatty() is supplied."""
    monkeypatch.setattr(setup_cmd, "sys", SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: True)))


def _env_lines(tmp_path: Path) -> dict[str, str]:
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    }


def _raven_config(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "raven.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


class TestPickModel:
    def test_the_pick_is_the_highest_gpu_tier_the_card_clears(self) -> None:
        tiers = setup_cmd._MODEL_TIER
        for threshold, model, _ in tiers:
            if not threshold:
                continue
            assert setup_cmd._pick_model(threshold, 8) == model
            expected_below = next(m for t, m, _ in tiers if t <= threshold - 1)
            assert setup_cmd._pick_model(threshold - 1, 8) == expected_below, threshold

    def test_a_cpu_only_box_is_sized_by_ram_alone(self) -> None:
        assert setup_cmd._pick_model(0, 32) == "llama3.1:8b"
        assert setup_cmd._pick_model(0, 16) == "llama3.2:3b"
        assert setup_cmd._pick_model(0, 8) == "llama3.2:1b"

    def test_no_pick_and_no_tier_it_generates_is_billed_by_a_provider(self) -> None:
        picks = {m for _, m, _ in setup_cmd._MODEL_TIER} | {"llama3.1:8b", "llama3.2:3b", "llama3.2:1b"}
        for pick in sorted(picks):
            assert "/" not in pick, pick
            for tier in setup_cmd._tier_models_for(pick).values():
                assert "/" not in tier, (pick, tier)
                assert tier in picks, (pick, tier)


class TestSetupWithoutFree:
    def test_usage_is_printed_and_no_file_is_written(self, tmp_path: Path, pulls: list[str]) -> None:
        result = CliRunner().invoke(setup_cmd.setup, [])
        assert result.exit_code == 0, result.output
        assert "raven setup --free" in result.output
        assert "--experimental" in result.output and "--model NAME" in result.output
        assert list(tmp_path.iterdir()) == []
        assert pulls == []


class TestFreeSetup:
    def test_every_model_string_it_writes_is_an_ollama_tag(self, tmp_path: Path, pulls: list[str]) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        assert pulls == ["llama3.1:8b"]

        llm = _raven_config(tmp_path)["llm"]
        assert llm["provider"] == "ollama"
        for name, value in llm.items():
            if "model" in name:
                assert value.startswith("ollama/"), (name, value)

        coded = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        assert coded["model"].startswith("ollama/")
        assert all(m.startswith("ollama/") for m in coded["providers"][0]["models"])

        env = _env_lines(tmp_path)
        for name in _WRITTEN_KEYS[:4]:
            assert env[name].startswith("ollama/"), (name, env[name])
        assert env["OLLAMA_BASE_URL"] == "http://localhost:11434"

    def test_the_features_the_panel_promises_are_the_ones_written(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        # The flags live where FeatureFlags reads them; raven.json never had a features reader, so the
        # summary used to promise dreaming while the gateway ran with it off.
        raw = yaml.safe_load((tmp_path / ".raven" / "features.yaml").read_text(encoding="utf-8"))
        assert raw["features"]["dreaming"] is True
        flags = FeatureFlags.load(tmp_path / ".raven" / "features.yaml")
        assert {"dreaming", "delegation", "planner", "skills"} <= set(flags.enabled_list())
        assert "features" not in _raven_config(tmp_path)
        coded = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        assert coded["experimental"] == {"dreaming": True, "delegation": True}
        # ravencode's resolver stops at opencode.json, so a second copy would be a file nothing reads.
        assert not (tmp_path / "ravencode.json").exists()

    def test_a_rerun_keeps_the_operators_own_feature_lines(self, tmp_path: Path) -> None:
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        path = tmp_path / ".raven" / "features.yaml"
        before = path.read_text(encoding="utf-8")
        assert "voice: true" not in before
        path.write_text(
            before.replace("skills: true", "skills: true\n  voice: true") + "# operator note\n",
            encoding="utf-8",
        )
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        after = path.read_text(encoding="utf-8")
        assert "voice: true" in after, "setup owns four flags, not the whole file"
        assert "# operator note" in after
        raw = yaml.safe_load(after)
        assert raw["features"]["dreaming"] is True

    def test_ravencode_is_repointed_at_the_model_the_switch_chose(self, tmp_path: Path, pulls: list[str]) -> None:
        """An existing opencode.json used to keep its old model, so the coding agent ignored the switch."""
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        before = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        assert before["model"] == "ollama/llama3.1:8b"
        assert before["providers"][0]["models"] == ["ollama/llama3.1:8b", "ollama/llama3.2:3b"]

        CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental", "--yes"])
        after = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        assert after["model"] == f"ollama/{HERETIC_HF_REF}"
        assert after["small_model"] == f"ollama/{HERETIC_HF_REF}"
        assert after["providers"][0]["models"] == [f"ollama/{HERETIC_HF_REF}", f"ollama/{HERETIC_HF_REF}"]
        assert after["temperature"] == before["temperature"] and after["max_steps"] == before["max_steps"]

    def test_an_existing_config_keeps_the_sections_this_command_does_not_own(self, tmp_path: Path) -> None:
        (tmp_path / "raven.json").write_text(
            json.dumps({"channels": {"telegram": {"token": "123:ABC"}}, "llm": {"default_model": "openrouter/x"}}),
            encoding="utf-8",
        )
        (tmp_path / "opencode.json").write_text(
            json.dumps({"mcp_servers": [{"id": "fs"}], "providers": [{"id": "openrouter", "models": ["a"]}]}),
            encoding="utf-8",
        )
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        raven_cfg = _raven_config(tmp_path)
        assert raven_cfg["channels"] == {"telegram": {"token": "123:ABC"}}
        assert raven_cfg["llm"]["default_model"] == "ollama/llama3.1:8b"
        coded = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
        assert coded["mcp_servers"] == [{"id": "fs"}]
        assert coded["providers"][0]["id"] == "openrouter", "the operator's own provider must survive"
        assert [p["id"] for p in coded["providers"]] == ["openrouter", "ollama"]

    def test_a_jsonc_config_is_left_alone_rather_than_flattened(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text(
            '{\n  // operator note\n  "model": "ollama/keepme"\n}\n', encoding="utf-8"
        )
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        assert "not plain JSON" in result.output
        assert "keepme" in (tmp_path / "opencode.json").read_text(encoding="utf-8")

    def test_the_workspace_directories_the_config_points_at_exist(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        cfg = _raven_config(tmp_path)
        # `plugins_dir`/`skills_dir` were read by nothing: the artifact resolver takes directories from
        # `paths`, so a directory named in the old keys was a setting that silently did nothing.
        assert "plugins_dir" not in cfg and "skills_dir" not in cfg
        for key in ("skills", "plugins"):
            assert cfg["paths"][key], key
        for directory in ("workspace", "plugins", "data"):
            assert (tmp_path / directory).is_dir(), directory
        assert ArtifactPaths.resolve(cwd=tmp_path).plugins == [tmp_path / "plugins"]

    def test_a_secret_key_is_generated_once_and_survives_the_next_run(self, tmp_path: Path) -> None:
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        key = _env_lines(tmp_path)["WEB_SECRET_KEY"]
        assert len(key) >= 32
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert text.count("WEB_SECRET_KEY=") == 1
        assert f"WEB_SECRET_KEY={key}" in text, "rotating the key on re-run logs out every session"

    def test_re_running_keeps_the_operators_own_keys(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text(
            "OPENROUTER_API_KEY=sk-or-keepme\nDEFAULT_MODEL=openrouter/x\n", encoding="utf-8"
        )
        CliRunner().invoke(setup_cmd.setup, ["--free"])
        text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "OPENROUTER_API_KEY=sk-or-keepme" in text
        assert text.count("DEFAULT_MODEL=") == 1 and "openrouter/x" not in text


class TestHardwareChain:
    def test_the_reading_of_the_box_drives_the_report_the_pick_and_the_download(
        self, tmp_path: Path, box: dict[str, Any], pulls: list[str]
    ) -> None:
        box["hw"] = Hardware(ram_total_gb=16.0, ram_free_gb=12.0, disk_free_gb=59.0, vram_mb=8192)
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        assert "8192 MB" in result.output and "16 GB (12.0 GB free now)" in result.output
        assert "59.0 GB free" in result.output
        assert pulls == ["llama3.1:8b"]
        assert _raven_config(tmp_path)["llm"]["default_model"] == "ollama/llama3.1:8b"

    def test_a_box_with_no_gpu_says_so_instead_of_quietly_running_cpu(self, box: dict[str, Any]) -> None:
        box["hw"] = _SMALL_BOX
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        assert "No NVIDIA GPU detected" in result.output
        assert "Not detected (CPU mode)" in result.output

    def test_setup_asks_the_shared_hardware_module_rather_than_probing_itself(self) -> None:
        """WMIC is gone from Windows 11 24H2 and answers zero; a local probe would pick the 1B model."""
        source = Path(setup_cmd.__file__).read_text(encoding="utf-8")
        assert "from raven.core.hardware import" in source
        for forbidden in ("wmic", "ctypes", "GlobalMemoryStatusEx", "sysconf", "nvidia-smi", "MEMORYSTATUSEX"):
            assert forbidden not in source, forbidden


class TestExperimentalFlag:
    def test_hardware_that_cannot_run_it_is_refused_before_anything_is_written(
        self, tmp_path: Path, box: dict[str, Any], pulls: list[str]
    ) -> None:
        box["hw"] = _SMALL_BOX
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental"])
        assert result.exit_code == 1, result.output
        assert "--experimental refused" in result.output
        assert HERETIC_HF_REF in result.output
        assert "4.0 GB free on the model volume" in result.output
        assert "0.9 GB RAM free with 0 MB of VRAM to offload to" in result.output
        assert list(tmp_path.iterdir()) == []
        assert pulls == []

    def test_yes_takes_the_experimental_model_and_pulls_it(
        self, tmp_path: Path, pulls: list[str], box: dict[str, Any]
    ) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental", "--yes"])
        assert result.exit_code == 0, result.output
        assert box["hw"] is _GOOD_BOX
        assert pulls == [HERETIC_HF_REF]
        assert _env_lines(tmp_path)["DEFAULT_MODEL"] == f"ollama/{HERETIC_HF_REF}"
        assert _raven_config(tmp_path)["llm"]["default_model"] == f"ollama/{HERETIC_HF_REF}"

    def test_every_tier_follows_the_experimental_model_so_nothing_left_behind_bills(
        self, tmp_path: Path, pulls: list[str]
    ) -> None:
        CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental", "--yes"])
        llm = _raven_config(tmp_path)["llm"]
        assert {llm["model_fast"], llm["model_balanced"], llm["model_quality"]} == {f"ollama/{HERETIC_HF_REF}"}
        assert pulls == [HERETIC_HF_REF]

    def test_a_scripted_run_never_starts_the_download_and_configures_what_the_box_runs(
        self, tmp_path: Path, pulls: list[str]
    ) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental"])
        assert result.exit_code == 0, result.output
        assert f"Not downloading {HERETIC_SIZE_GB:.2f} GB without a yes" in result.output
        assert "raven models enable-heretic" in result.output
        assert pulls == ["llama3.1:8b"], "the fallback is the model this hardware runs, and it is pulled"
        assert "Configuring llama3.1:8b" in result.output
        assert HERETIC_HF_REF not in (tmp_path / ".env").read_text(encoding="utf-8")
        assert _raven_config(tmp_path)["llm"]["default_model"] == "ollama/llama3.1:8b"

    def test_declining_the_prompt_configures_no_switch_for_absent_weights(
        self, tmp_path: Path, pulls: list[str], tty: None
    ) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental"], input="n\n")
        assert result.exit_code == 0, result.output
        assert "Download declined" in result.output
        assert pulls == ["llama3.1:8b"]
        assert HERETIC_HF_REF not in (tmp_path / ".env").read_text(encoding="utf-8")
        assert _raven_config(tmp_path)["llm"]["default_model"] == "ollama/llama3.1:8b"

    def test_accepting_the_prompt_downloads_and_switches(self, pulls: list[str], tty: None) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental"], input="y\n")
        assert result.exit_code == 0, result.output
        assert f"Download {HERETIC_SIZE_GB:.2f} GB into Ollama" in result.output
        assert pulls == [HERETIC_HF_REF]

    def test_the_prompt_shows_the_weight_size_and_this_boxes_numbers(self, tty: None) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--experimental"], input="n\n")
        assert f"{HERETIC_SIZE_GB:.2f} GB" in result.output
        assert _GOOD_BOX.summary() in result.output


@pytest.fixture
def real_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the real downloader; the module fixture stubs it so no other test can move a byte."""
    monkeypatch.setattr(setup_cmd, "_pull_model", _REAL_PULL)


class TestPullOutcome:
    """A failed download must not be reported as a ready stack, and must not end in a traceback."""

    def test_a_failed_pull_writes_the_config_but_exits_one_and_says_weights_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(setup_cmd, "_pull_model", lambda model: False)
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 1, result.output
        assert "weights missing" in result.output
        assert "NOT pulled" in result.output and "ollama pull llama3.1:8b" in result.output
        assert "Free Local AI Stack — Ready" not in result.output
        assert _raven_config(tmp_path)["llm"]["default_model"] == "ollama/llama3.1:8b"

    def test_a_successful_pull_is_reported_ready(self, tmp_path: Path, pulls: list[str]) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free"])
        assert result.exit_code == 0, result.output
        assert "Free Local AI Stack — Ready" in result.output
        assert pulls == ["llama3.1:8b"]
        assert (tmp_path / ".env").exists()

    def test_the_pull_shows_ollamas_own_progress_instead_of_a_blind_spinner(
        self, monkeypatch: pytest.MonkeyPatch, real_pull: None
    ) -> None:
        seen: dict[str, Any] = {}

        def _run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            seen["argv"] = argv
            seen["kwargs"] = kwargs
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(subprocess, "run", _run)
        assert setup_cmd._pull_model("qwen2.5:32b") is True
        assert seen["argv"] == ["C:/fake/ollama.exe", "pull", "qwen2.5:32b"]
        assert not seen["kwargs"].get("capture_output"), "5.63 GB behind a captured pipe looks like a hang"
        assert seen["kwargs"]["timeout"] == 1800

    def test_a_pull_that_outlives_the_timeout_says_how_to_resume(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], real_pull: None
    ) -> None:
        def _slow(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

        monkeypatch.setattr(subprocess, "run", _slow)
        assert setup_cmd._pull_model("qwen2.5:32b") is False
        assert "resume with: ollama pull qwen2.5:32b" in capsys.readouterr().out

    def test_a_nonzero_pull_exit_is_a_failure_not_a_success(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], real_pull: None
    ) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr=""))
        assert setup_cmd._pull_model("qwen2.5:32b") is False
        assert "Retry with: ollama pull qwen2.5:32b" in capsys.readouterr().out

    def test_a_missing_binary_cannot_start_a_pull(self, monkeypatch: pytest.MonkeyPatch, real_pull: None) -> None:
        monkeypatch.setattr(setup_cmd, "_find_ollama", lambda: None)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("pulled without an ollama binary"))
        assert setup_cmd._pull_model("qwen2.5:32b") is False


class TestModelOverride:
    def test_forced_model_beats_the_hardware_pick_and_the_experimental_flag(
        self, tmp_path: Path, pulls: list[str]
    ) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--model", "qwen2.5:32b", "--experimental", "--yes"])
        assert result.exit_code == 0, result.output
        assert pulls == ["qwen2.5:32b"]
        assert _raven_config(tmp_path)["llm"]["default_model"] == "ollama/qwen2.5:32b"
        assert HERETIC_HF_REF not in (tmp_path / ".env").read_text(encoding="utf-8")

    def test_a_forced_model_still_fills_its_tiers_from_the_known_table(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(setup_cmd.setup, ["--free", "--model", "qwen2.5:32b"])
        assert result.exit_code == 0, result.output
        llm = _raven_config(tmp_path)["llm"]
        assert llm["model_fast"] == "ollama/llama3.2:3b"
        assert llm["model_balanced"] == "ollama/qwen2.5:14b"
        assert llm["model_quality"] == "ollama/qwen2.5:32b"
