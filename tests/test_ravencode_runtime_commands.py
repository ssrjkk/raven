from __future__ import annotations

from pathlib import Path

from ravencode.runtime.commands import CustomCommand, commands_from_config, discover_commands


def _write_cmd(dir_path: Path, name: str, body: str) -> Path:
    f = dir_path / f"{name}.md"
    f.write_text(body, encoding="utf-8")
    return f


class TestFromMarkdown:
    def test_valid_frontmatter(self, tmp_path) -> None:
        f = _write_cmd(
            tmp_path,
            "review",
            "---\nprompt: Do a review\ndescription: Review code\nagent: coder\nmodel: gpt-x\nsubtask: true\n---\nbody",
        )
        cmd = CustomCommand.from_markdown(f)
        assert cmd is not None
        assert cmd.name == "review"
        assert cmd.prompt == "Do a review"
        assert cmd.description == "Review code"
        assert cmd.agent == "coder"
        assert cmd.model == "gpt-x"
        assert cmd.subtask is True
        assert cmd.source == str(f)

    def test_prompt_falls_back_to_body(self, tmp_path) -> None:
        f = _write_cmd(tmp_path, "plain", "---\ndescription: d\n---\nUse this text")
        cmd = CustomCommand.from_markdown(f)
        assert cmd is not None
        assert cmd.prompt == "Use this text"
        assert cmd.description == "d"

    def test_missing_frontmatter(self, tmp_path) -> None:
        f = _write_cmd(tmp_path, "no", "no frontmatter here")
        assert CustomCommand.from_markdown(f) is None

    def test_invalid_frontmatter_split(self, tmp_path) -> None:
        f = _write_cmd(tmp_path, "bad", "---\nonly one delimiter")
        assert CustomCommand.from_markdown(f) is None

    def test_bad_yaml(self, tmp_path) -> None:
        f = _write_cmd(tmp_path, "bad_yaml", "---\nnot: [valid\n---\nbody")
        cmd = CustomCommand.from_markdown(f)
        assert cmd is not None
        assert cmd.prompt == "body"

    def test_meta_not_dict(self, tmp_path) -> None:
        f = _write_cmd(tmp_path, "list_meta", "---\n- one\n- two\n---\nbody")
        cmd = CustomCommand.from_markdown(f)
        assert cmd is not None
        assert cmd.prompt == "body"


class TestRenderPrompt:
    def test_substitutions(self) -> None:
        cmd = CustomCommand(name="x", prompt="$ARGUMENTS [$1] [$2] [$3]")
        assert cmd.render_prompt("alpha beta") == "alpha beta [alpha] [beta] []"

    def test_file_refs(self) -> None:
        cmd = CustomCommand(name="x", prompt="see @main.py")
        assert cmd.render_prompt(file_refs={"main.py": "print(1)"}) == "see \n```\nprint(1)\n```\n"

    def test_no_args(self) -> None:
        cmd = CustomCommand(name="x", prompt="$1 and $ARGUMENTS")
        assert cmd.render_prompt() == " and "

    def test_no_refs(self) -> None:
        cmd = CustomCommand(name="x", prompt="@a @b")
        assert cmd.render_prompt() == "@a @b"


class TestDiscoverCommands:
    def test_discovers_sorted(self, tmp_path) -> None:
        (tmp_path / "b.md").write_text("---\nprompt: B\n---\n", encoding="utf-8")
        (tmp_path / "a.md").write_text("---\nprompt: A\n---\n", encoding="utf-8")
        result = discover_commands([tmp_path])
        assert list(result) == ["a", "b"]

    def test_skips_invalid(self, tmp_path) -> None:
        (tmp_path / "ok.md").write_text("---\nprompt: P\n---\n", encoding="utf-8")
        (tmp_path / "bad.md").write_text("no frontmatter", encoding="utf-8")
        result = discover_commands([tmp_path])
        assert list(result) == ["ok"]

    def test_missing_dir_skipped(self) -> None:
        assert discover_commands([Path("does_not_exist_xyz")]) == {}

    def test_no_extra_dirs(self) -> None:
        result = discover_commands()
        assert isinstance(result, dict)


class TestCommandsFromConfig:
    def test_basic(self) -> None:
        result = commands_from_config(
            [{"name": "review", "prompt": "Review", "description": "d", "agent": "a", "subtask": True, "source": "s"}]
        )
        assert result["review"].prompt == "Review"
        assert result["review"].description == "d"
        assert result["review"].agent == "a"
        assert result["review"].subtask is True

    def test_template_fallback(self) -> None:
        result = commands_from_config([{"name": "t", "template": "template text"}])
        assert result["t"].prompt == "template text"

    def test_missing_name_skipped(self) -> None:
        result = commands_from_config([{"prompt": "no name"}, {"name": "ok", "prompt": "P"}])
        assert list(result) == ["ok"]

    def test_defaults(self) -> None:
        result = commands_from_config([{"name": "x", "prompt": "P"}])
        cmd = result["x"]
        assert cmd.description == ""
        assert cmd.agent == ""
        assert cmd.model == ""
        assert cmd.subtask is False
        assert cmd.source == "config"
