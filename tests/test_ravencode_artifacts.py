from __future__ import annotations

from pathlib import Path

from ravencode.runtime.agent_core import AgentConfig, ReActAgent


def test_artifact_blocks_in_system_prompt(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "AGENTS.md").write_text("Project level rule.", encoding="utf-8")
    rule_dir = tmp_path / ".raven" / "rules"
    rule_dir.mkdir(parents=True)
    (rule_dir / "root.md").write_text("# Root\nAlways lint before commit.", encoding="utf-8")
    skill_dir = tmp_path / ".raven" / "skills" / "polish"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: Polish code\n---\nRun the linter on changed files.", encoding="utf-8"
    )
    cmd_dir = tmp_path / ".raven" / "commands" / "shipit"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "command.md").write_text(
        "---\nname: shipit\ndescription: Build and deploy\nprompt: Build and deploy now\n---", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    agent = ReActAgent(config=AgentConfig())
    prompt = agent.conversation.system_prompt

    assert "[project rules]" in prompt
    assert "Always lint before commit." in prompt
    assert "Project level rule." in prompt
    assert "[skill: polish]" in prompt
    assert "Run the linter on changed files." in prompt
    assert "[available commands]" in prompt
    assert "/shipit" in prompt


def test_artifact_blocks_empty_without_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    agent = ReActAgent(config=AgentConfig())
    assert "[project rules]" not in agent.conversation.system_prompt
