from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
_DOC_CITE = re.compile(r"^\| `(\w+)` \| (on|off) \| `(RAVEN_FEATURE_[A-Z_]+)` \| .*? - `([\w/.]+):(\d+)` \|", re.M)
_ENABLED_CALL = re.compile(r"is_enabled\(\s*[\"'](\w+)[\"']")


def _raven_flags() -> dict[str, str]:
    from raven.core.features import env_flag_names

    return env_flag_names()


def _ravencode_flags() -> list[str]:
    from ravencode.core.feature_flags import FeatureFlags

    return list(FeatureFlags().all_flags())


def _consulted_names(search_dirs: tuple[str, ...], skip: tuple[str, ...]) -> set[str]:
    """Every flag name some code asks about, found in `is_enabled("<name>")` call sites."""
    found: set[str] = set()
    for directory in search_dirs:
        for path in (ROOT / directory).rglob("*.py"):
            if any(part in path.as_posix() for part in skip):
                continue
            found.update(_ENABLED_CALL.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return found


def test_every_declared_flag_is_asked_about_by_some_code() -> None:
    raven_flags = set(_raven_flags())
    consulted_raven = _consulted_names(("raven", "aios"), ("raven/core/features.py",))
    assert sorted(raven_flags - consulted_raven) == [], sorted(raven_flags - consulted_raven)

    ravencode_flags = set(_ravencode_flags())
    consulted_ravencode = _consulted_names(("ravencode",), ("ravencode/core/feature_flags.py",))
    assert sorted(ravencode_flags - consulted_ravencode) == [], sorted(ravencode_flags - consulted_ravencode)


def test_the_example_env_lists_exactly_the_switches_the_code_reads() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\s*#?\s*(RAVEN_FEATURE_[A-Z_]+)\s*=", text, re.M))
    assert documented == set(_raven_flags().values())


def test_the_documented_table_matches_the_defaults_and_the_citations() -> None:
    from raven.core.features import FeatureFlags

    doc = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    rows = _DOC_CITE.findall(doc)
    assert len(rows) == len(_raven_flags()), rows

    defaults = FeatureFlags().to_dict()
    for name, stated_default, env_var, source_file, line_no in rows:
        assert env_var == _raven_flags()[name], (name, env_var)
        assert defaults[name] is (stated_default == "on"), (name, stated_default, defaults[name])
        lines = (ROOT / source_file).read_text(encoding="utf-8").splitlines()
        cited = lines[int(line_no) - 1]
        assert f'is_enabled("{name}")' in cited or f"is_enabled('{name}')" in cited, (source_file, line_no, cited)


def test_the_environment_overrides_the_file_and_refuses_garbage(
    tmp_path: pathlib.Path, monkeypatch: Any
) -> None:
    from raven.core.features import FeatureFlags

    config = tmp_path / "features.yaml"
    config.write_text("features:\n  voice: true\n", encoding="utf-8")

    monkeypatch.delenv("RAVEN_FEATURE_VOICE", raising=False)
    monkeypatch.delenv("RAVEN_FEATURE_PLANNER", raising=False)
    monkeypatch.delenv("RAVEN_FEATURE_SKILLS", raising=False)

    loaded = FeatureFlags.load(config)
    assert loaded.voice is True

    monkeypatch.setenv("RAVEN_FEATURE_VOICE", "off")
    monkeypatch.setenv("RAVEN_FEATURE_PLANNER", "on")
    loaded = FeatureFlags.load(config)
    assert loaded.voice is False, "the environment did not override the file"
    assert loaded.planner is True

    monkeypatch.setenv("RAVEN_FEATURE_SKILLS", "maybe")
    loaded = FeatureFlags.load(config)
    assert loaded.skills is True, "an unparseable value must not flip the flag"


def test_unknown_keys_in_the_file_are_ignored_not_applied(tmp_path: pathlib.Path) -> None:
    from raven.core.features import FeatureFlags

    config = tmp_path / "features.yaml"
    config.write_text("features:\n  to_dict: false\n  enabled_list: 1\n", encoding="utf-8")
    flags = FeatureFlags.load(config)
    assert callable(flags.to_dict) and callable(flags.enabled_list)
    assert flags.to_dict() == FeatureFlags().to_dict()


def test_raven_init_writes_only_flags_the_loader_accepts(tmp_path: pathlib.Path) -> None:
    from raven.cli import init_cmd

    team = tmp_path / ".raven"
    team.mkdir()
    init_cmd._write_features_yaml(team)
    raw: dict[str, Any] = yaml.safe_load((team / "features.yaml").read_text(encoding="utf-8"))
    assert set(raw["features"]) == set(_raven_flags())
    assert set(raw["features"]) <= set(_consulted_names(("raven", "aios"), ("raven/core/features.py",)))
