from __future__ import annotations

import json
from pathlib import Path

import pytest

from raven.core.artifacts.paths import KINDS, ArtifactPaths, _read_raven_json


def _touch(base: Path, kind: str) -> None:
    (base / kind).mkdir(parents=True, exist_ok=True)


def test_layered_resolution_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    global_base = home / ".config" / "raven"
    team = tmp_path / ".raven"
    personal = tmp_path / ".raven.local"
    for kind in ("skills", "commands", "rules"):
        _touch(global_base, kind)
        _touch(team, kind)
        _touch(personal, kind)

    paths = ArtifactPaths.resolve(cwd=tmp_path, home=home)
    skills = paths.skills
    assert skills[0] == (personal / "skills").resolve()
    assert skills[1] == (team / "skills").resolve()
    assert skills[-1] == (global_base / "skills").resolve()


def test_env_override_highest_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_dir = tmp_path / "env-skills"
    env_dir.mkdir()
    (tmp_path / ".raven" / "skills").mkdir(parents=True)
    monkeypatch.setenv("RAVEN_SKILLS_DIR", str(env_dir))

    paths = ArtifactPaths.resolve(cwd=tmp_path)
    assert paths.skills[0] == env_dir.resolve()


def test_config_override_from_raven_json(tmp_path: Path) -> None:
    cfg_dir = tmp_path / "cfg-skills"
    cfg_dir.mkdir()
    (tmp_path / "raven.json").write_text('{"paths": {"skills": ["cfg-skills"]}}', encoding="utf-8")
    paths = ArtifactPaths.resolve(cwd=tmp_path)
    assert paths.skills[0] == cfg_dir.resolve()


def test_personal_overrides_team_on_conflict(tmp_path: Path) -> None:
    (tmp_path / ".raven" / "skills").mkdir(parents=True)
    (tmp_path / ".raven.local" / "skills").mkdir(parents=True)
    paths = ArtifactPaths.resolve(cwd=tmp_path)
    assert paths.skills[0] == (tmp_path / ".raven.local" / "skills").resolve()
    assert paths.skills[1] == (tmp_path / ".raven" / "skills").resolve()


def test_missing_dirs_skipped(tmp_path: Path) -> None:
    paths = ArtifactPaths.resolve(cwd=tmp_path)
    assert paths.skills == []
    assert paths.commands == []


def test_legacy_compat_dirs_are_last(tmp_path: Path) -> None:
    (tmp_path / "workspace" / "skills").mkdir(parents=True)
    paths = ArtifactPaths.resolve(cwd=tmp_path)
    assert paths.skills and paths.skills[-1] == (tmp_path / "workspace" / "skills").resolve()


def test_dedupe(tmp_path: Path) -> None:
    (tmp_path / ".raven" / "skills").mkdir(parents=True)
    monkeypatch_env = {"RAVEN_SKILLS_DIR": str(tmp_path / ".raven" / "skills")}
    paths = ArtifactPaths.resolve(cwd=tmp_path, env=monkeypatch_env)
    assert len(paths.skills) == paths.skills.count(paths.skills[0]) == 1


def test_plain_env_var_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_dir = tmp_path / "plain-skills"
    env_dir.mkdir()
    monkeypatch.setenv("SKILLS_DIR", str(env_dir))
    paths = ArtifactPaths.resolve(cwd=tmp_path)
    assert paths.skills[0] == env_dir.resolve()


def test_read_raven_json_invalid(tmp_path: Path) -> None:
    (tmp_path / "raven.json").write_text("not json", encoding="utf-8")
    assert _read_raven_json(tmp_path, {}) == {}


def test_the_raven_json_the_onboarding_clis_write_is_the_one_the_resolver_reads(tmp_path: Path) -> None:
    """`raven init` used to emit `plugins_dir` and `skills_dir` beside `paths`, and nothing read them.

    An operator who set them got a second, inert answer to a question the resolver had already asked, so
    the onboarding output is checked against the layers this module actually resolves.
    """
    from raven.cli.init_cmd import _write_raven_json

    _write_raven_json(
        {"provider": "openrouter", "default_model": "openrouter/openai/gpt-4o"},
        {"telegram": {"enabled": True, "token": "t"}},
        {"dm_policy": "pairing"},
        tmp_path / "raven.json",
    )
    data = json.loads((tmp_path / "raven.json").read_text(encoding="utf-8"))
    assert "plugins_dir" not in data and "skills_dir" not in data
    assert set(data["paths"]) == set(KINDS)
    (tmp_path / "plugins").mkdir()
    paths = ArtifactPaths.resolve(cwd=tmp_path, env={})
    assert paths.plugins[0] == (tmp_path / "plugins").resolve()
