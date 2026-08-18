from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import ravencode.config.loader as loader
from ravencode.config.loader import (
    ConfigLoader,
    RavenConfig,
    deep_merge,
    get_config,
    load_config_file,
    resolve_variables,
    resolve_vars_in_dict,
    strip_jsonc,
)


@pytest.fixture(autouse=True)
def _reset_global_config():
    loader._config_instance = None
    loader._CONFIG_PATHS.clear()
    yield
    loader._config_instance = None
    loader._CONFIG_PATHS.clear()


class TestResolveVariables:
    def test_env_var_resolved(self, monkeypatch) -> None:
        monkeypatch.setenv("RV_TEST_KEY", "value123")
        assert resolve_variables("{env:RV_TEST_KEY}") == "value123"

    def test_env_var_default(self, monkeypatch) -> None:
        monkeypatch.delenv("RV_MISSING", raising=False)
        assert resolve_variables("{env:RV_MISSING:fallback}") == "fallback"

    def test_env_var_no_default(self, monkeypatch) -> None:
        monkeypatch.delenv("RV_MISSING", raising=False)
        assert resolve_variables("{env:RV_MISSING}") == ""

    def test_file_variable_reads_file(self, tmp_path: Path) -> None:
        f = tmp_path / "key.txt"
        f.write_text("  secret  \n", encoding="utf-8")
        assert resolve_variables(f"{{file:{f}}}") == "secret"

    def test_file_variable_missing(self) -> None:
        assert resolve_variables("{file:Z:/does/not/exist.txt}") == ""

    def test_unrelated_text_untouched(self) -> None:
        assert resolve_variables("plain text no vars") == "plain text no vars"


class TestResolveVarsInDict:
    def test_nested_resolution(self, monkeypatch) -> None:
        monkeypatch.setenv("RV_NEST", "nested-value")
        data: Any = {"a": "{env:RV_NEST}", "b": [{"c": "{env:RV_NEST}"}], "d": 5, "e": None}
        result = resolve_vars_in_dict(data)
        assert result["a"] == "nested-value"
        assert result["b"][0]["c"] == "nested-value"
        assert result["d"] == 5
        assert result["e"] is None


class TestStripJsonc:
    def test_comment_only_line_removed(self) -> None:
        text = '{\n  "a": 1,\n  // trailing note\n  "b": 2\n}'
        assert strip_jsonc(text) == '{\n  "a": 1,\n  "b": 2\n}'

    def test_inline_comment_stripped(self) -> None:
        text = '{"a": 1} // comment'
        assert strip_jsonc(text) == '{"a": 1}'

    def test_hash_inline_comment_stripped(self) -> None:
        text = '{"a": 1} # hash comment'
        assert strip_jsonc(text) == '{"a": 1}'

    def test_plain_lines_preserved(self) -> None:
        text = '{\n"a": 1\n}'
        assert strip_jsonc(text) == '{\n"a": 1\n}'

    def test_empty_lines_become_blank(self) -> None:
        assert strip_jsonc("\n\n") == "\n"


class TestDeepMerge:
    def test_nested_dict_merge(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "keep": "v"}
        overlay = {"a": {"y": 9}, "new": 3}
        result = deep_merge(base, overlay)
        assert result == {"a": {"x": 1, "y": 9}, "keep": "v", "new": 3}
        assert base == {"a": {"x": 1, "y": 2}, "keep": "v"}

    def test_scalar_overwrite(self) -> None:
        assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}


class TestLoadJsonc:
    def test_missing_file_returns_empty(self) -> None:
        assert loader._load_jsonc(Path("Z:/definitely/missing.json")) == {}

    def test_loads_jsonc_file(self, tmp_path: Path) -> None:
        f = tmp_path / "cfg.json"
        f.write_text('{\n  "model": "m", // inline\n  "theme": "nord"\n}', encoding="utf-8")
        assert loader._load_jsonc(f) == {"model": "m", "theme": "nord"}


class TestDefaultConfigPaths:
    def test_project_json(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
        paths = loader._default_config_paths(tmp_path)
        assert ("project", (tmp_path / "opencode.json").resolve()) in paths

    def test_project_jsonc_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "ravencode.jsonc").write_text("{}", encoding="utf-8")
        paths = loader._default_config_paths(tmp_path)
        assert ("project", (tmp_path / "ravencode.jsonc").resolve()) in paths

    def test_global_config(self, tmp_path: Path, monkeypatch) -> None:
        global_cfg = tmp_path / ".config" / "opencode" / "opencode.json"
        global_cfg.parent.mkdir(parents=True)
        global_cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        paths = loader._default_config_paths(tmp_path / "proj")
        assert ("global", global_cfg) in paths

    def test_env_config_path(self, monkeypatch, tmp_path: Path) -> None:
        env_cfg = tmp_path / "env.json"
        env_cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("OPENCODE_CONFIG", str(env_cfg))
        paths = loader._default_config_paths(tmp_path / "proj")
        assert ("env", env_cfg) in paths

    def test_dot_dir_config(self, tmp_path: Path) -> None:
        dot = tmp_path / ".opencode"
        dot.mkdir()
        (dot / "config.json").write_text("{}", encoding="utf-8")
        paths = loader._default_config_paths(tmp_path)
        assert ("dot_opencode", dot / "config.json") in paths

    def test_dot_ravencode_config(self, tmp_path: Path) -> None:
        dot = tmp_path / ".ravencode"
        dot.mkdir()
        (dot / "config.json").write_text("{}", encoding="utf-8")
        paths = loader._default_config_paths(tmp_path)
        assert ("dot_ravencode", dot / "config.json") in paths

    def test_inline_config(self, monkeypatch) -> None:
        monkeypatch.setenv("RAVENCODE_CONFIG_CONTENT", '{"model": "inline-model"}')
        paths = loader._default_config_paths(Path.cwd())
        inline = [p for name, p in paths if name == "inline"]
        assert len(inline) == 1
        assert Path(inline[0]).read_text(encoding="utf-8") == '{"model": "inline-model"}'

    def test_add_source(self) -> None:
        loader._add_source("name", Path("p"))
        assert ("name", Path("p")) in loader._CONFIG_PATHS


class TestRavenConfig:
    def test_from_dict_defaults(self) -> None:
        cfg = RavenConfig.from_dict({})
        assert cfg.model == ""
        assert cfg.max_steps == 30
        assert cfg.temperature == 0.7
        assert cfg.providers == []
        assert cfg.experimental == {}

    def test_to_dict_roundtrip(self) -> None:
        cfg = RavenConfig.from_dict({"model": "m", "max_steps": 5, "theme": "nord"})
        d = cfg.to_dict()
        assert d["model"] == "m"
        assert d["max_steps"] == 5
        assert d["theme"] == "nord"
        assert d["temperature"] == 0.7

    def test_resolve_providers(self) -> None:
        cfg = RavenConfig.from_dict(
            {
                "providers": [
                    {"id": "p1", "name": "Prov", "api_key": "k", "base_url": "http://x", "models": ["a"], "options": {"o": 1}},
                    {"id": "p2"},
                ]
            }
        )
        providers = cfg.resolve_providers()
        assert len(providers) == 2
        assert providers[0].id == "p1"
        assert providers[0].models == ["a"]
        assert providers[0].options == {"o": 1}
        assert providers[1].name == ""

    def test_resolve_agents(self) -> None:
        cfg = RavenConfig.from_dict(
            {
                "agents": [
                    {
                        "name": "sub",
                        "type": "subagent",
                        "description": "d",
                        "prompt": "p",
                        "model": "m",
                        "temperature": 0.2,
                        "max_steps": 7,
                        "permissions": {"write": "ask"},
                        "disabled": True,
                        "hidden": True,
                        "options": {"k": "v"},
                    }
                ]
            }
        )
        agents = cfg.resolve_agents()
        assert len(agents) == 1
        a = agents[0]
        assert a.name == "sub"
        assert a.temperature == 0.2
        assert a.max_steps == 7
        assert a.permissions == {"write": "ask"}
        assert a.disabled is True
        assert a.hidden is True
        assert a.options == {"k": "v"}


class TestConfigLoader:
    def test_discover(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
        loader_inst = ConfigLoader(tmp_path)
        assert ("project", tmp_path / "opencode.json") in loader_inst.discover()

    def test_load_all_merges_sources(self, tmp_path: Path, monkeypatch) -> None:
        (tmp_path / "opencode.json").write_text(
            json.dumps({"model": "proj-model", "theme": "nord", "nested": {"a": 1}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("RAVENCODE_MODEL", "env-model")
        loader_inst = ConfigLoader(tmp_path)
        cfg = loader_inst.load_all()
        assert cfg.model == "env-model"
        assert cfg.theme == "nord"
        assert loader._config_instance is cfg
        assert "env_overrides" in cfg._source

    def test_load_all_skips_bad_json(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text("{invalid", encoding="utf-8")
        loader_inst = ConfigLoader(tmp_path)
        cfg = loader_inst.load_all()
        assert cfg.model == ""

    def test_env_overrides_temperature_and_steps(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("RAVENCODE_TEMPERATURE", "0.5")
        monkeypatch.setenv("RAVENCODE_MAX_STEPS", "99")
        monkeypatch.setenv("RAVENCODE_THEME", "catppuccin")
        monkeypatch.setenv("RAVENCODE_TEMPERATURE_BAD", "not-a-float")
        loader_inst = ConfigLoader(tmp_path)
        cfg = loader_inst.load_all()
        assert cfg.temperature == 0.5
        assert cfg.max_steps == 99
        assert cfg.theme == "catppuccin"

    def test_env_overrides_ignore_bad_values(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("RAVENCODE_TEMPERATURE", "abc")
        monkeypatch.setenv("RAVENCODE_MAX_STEPS", "xyz")
        loader_inst = ConfigLoader(tmp_path)
        cfg = loader_inst.load_all()
        assert cfg.temperature == 0.7
        assert cfg.max_steps == 30

    def test_config_property_lazy_loads(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text(json.dumps({"model": "lazy"}), encoding="utf-8")
        loader_inst = ConfigLoader(tmp_path)
        assert loader_inst._merged is None
        cfg = loader_inst.config
        assert cfg.model == "lazy"
        assert loader_inst.config is cfg

    def test_reload(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "opencode.json"
        cfg_file.write_text(json.dumps({"model": "v1"}), encoding="utf-8")
        loader_inst = ConfigLoader(tmp_path)
        assert loader_inst.load_all().model == "v1"
        cfg_file.write_text(json.dumps({"model": "v2"}), encoding="utf-8")
        reloaded = loader_inst.reload()
        assert reloaded.model == "v2"

    def test_get_source_paths(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
        loader_inst = ConfigLoader(tmp_path)
        assert loader_inst.get_source_paths() == loader_inst.discover()


class TestModuleFunctions:
    def test_load_config_file(self, tmp_path: Path) -> None:
        f = tmp_path / "single.json"
        f.write_text(json.dumps({"model": "single", "max_steps": 12}), encoding="utf-8")
        cfg = load_config_file(f)
        assert cfg.model == "single"
        assert cfg.max_steps == 12
        assert cfg._source == str(f.resolve())

    def test_get_config_loads_with_project_dir(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text(json.dumps({"model": "proj"}), encoding="utf-8")
        cfg = get_config(tmp_path)
        assert cfg.model == "proj"
        assert loader._config_instance is cfg

    def test_get_config_caches(self, tmp_path: Path) -> None:
        (tmp_path / "opencode.json").write_text(json.dumps({"model": "proj"}), encoding="utf-8")
        first = get_config(tmp_path)
        assert get_config() is first
        assert get_config() is get_config()
