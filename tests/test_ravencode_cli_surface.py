"""Coverage for the ravencode CLI command surface and the TUI slash-command loop."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextvars import Token
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner
from rich.console import Console
from rich.prompt import Prompt

from raven.core.config import settings
from ravencode.agents.custom_agents import CustomAgentDef
from ravencode.agents.orchestrator import AgentType, Orchestrator
from ravencode.cli import main as cli_main
from ravencode.cli import tui
from ravencode.runtime import agent_core as agent_mod
from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.commands import CustomCommand


@pytest.fixture(autouse=True)
def _isolate_session_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The TUI keeps one live agent; the runtime keeps the last constructed one."""
    monkeypatch.setattr(tui, "_session_agent", None)
    token: Token[ReActAgent | None] = agent_mod._last_agent_var.set(None)
    yield
    agent_mod._last_agent_var.reset(token)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Session commands default to the data dir, so pin it instead of relying on the cwd."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "data" / "raven.db"))


def _invoke(*args: str, input: str = "") -> Any:
    return CliRunner().invoke(cli_main.cli, list(args), input=input)


def _sessions(tmp_path: Path) -> Path:
    sessions = tmp_path / "data" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions


class TestSessionCommands:
    def test_list_without_directory(self) -> None:
        assert "No sessions directory found" in _invoke("session", "list").output

    def test_list_shows_named_and_corrupt_entries(self, tmp_path: Path) -> None:
        sessions = _sessions(tmp_path)
        (sessions / "ok.json").write_text(json.dumps({"name": "auth run", "steps": 4}), encoding="utf-8")
        (sessions / "bad.json").write_text("{oops", encoding="utf-8")
        output = _invoke("session", "list").output
        assert "Sessions (2)" in output
        assert "auth run" in output
        assert "(corrupt)" in output

    def test_delete_existing_and_missing(self, tmp_path: Path) -> None:
        target = _sessions(tmp_path) / "x.json"
        target.write_text("{}", encoding="utf-8")
        assert _invoke("session", "delete", "x").exit_code == 0
        assert not target.exists()
        missing = _invoke("session", "delete", "x")
        assert missing.exit_code == 1
        assert "not found" in missing.output

    def test_export_sanitizes_secrets(self, tmp_path: Path) -> None:
        (_sessions(tmp_path) / "s9.json").write_text(
            json.dumps({"api_key": "sk-live", "nested": {"token": "t"}, "keep": 1}), encoding="utf-8"
        )
        out = tmp_path / "out.json"
        result = _invoke("session", "export", "s9", "--sanitize", "-o", str(out))
        assert result.exit_code == 0, result.output
        exported = json.loads(out.read_text(encoding="utf-8"))
        assert exported["api_key"] == "***"
        assert exported["nested"]["token"] == "***"
        assert exported["keep"] == 1

    def test_export_missing_session(self) -> None:
        result = _invoke("session", "export", "nope")
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_top_level_export_without_id_is_a_hint(self) -> None:
        assert "ravencode session export" in _invoke("export").output

    def test_resume_forwards_the_session_id_to_the_tui(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(cli_main, "tui_run", lambda **kw: seen.update(kw))
        _invoke("session", "resume", "abc123")
        assert seen == {"session_id": "abc123"}

    def test_delete_rejects_session_id_that_escapes_the_dir(self, tmp_path: Path) -> None:
        _sessions(tmp_path)
        victim = tmp_path / "data" / "victim.json"
        victim.write_text("{}", encoding="utf-8")
        result = _invoke("session", "delete", "../victim")
        assert result.exit_code == 1
        assert "Invalid session id" in result.output
        assert victim.exists()

    def test_export_rejects_session_id_that_escapes_the_dir(self, tmp_path: Path) -> None:
        _sessions(tmp_path)
        other = tmp_path / "data" / "other.json"
        other.write_text(json.dumps({"api_key": "sk-abcdefghij"}), encoding="utf-8")
        out = tmp_path / "out.json"
        result = _invoke("session", "export", "../other", "-o", str(out))
        assert result.exit_code == 1
        assert "Invalid session id" in result.output
        assert not out.exists()

    def test_import_rejects_session_id_from_the_payload(self, tmp_path: Path) -> None:
        _sessions(tmp_path)
        payload = tmp_path / "payload.json"
        payload.write_text(json.dumps({"id": "../overwritten", "steps": 2}), encoding="utf-8")
        result = _invoke("session", "import", str(payload))
        assert result.exit_code == 1
        assert "Invalid session id" in result.output
        assert not (tmp_path / "data" / "overwritten.json").exists()

    def test_import_falls_back_to_imported_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        payload = Path("payload.json")
        payload.write_text(json.dumps({"steps": 1}), encoding="utf-8")
        result = _invoke("session", "import", str(payload), "--dir", "sessions")
        assert result.exit_code == 0, result.output
        assert json.loads(Path("sessions/imported.json").read_text(encoding="utf-8")) == {"steps": 1}


class TestTuiCommand:
    def test_missing_project_directory_is_a_clean_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = _invoke("tui", "no-such-project")
        assert result.exit_code == 1
        assert "No such directory: no-such-project" in result.output

    def test_project_directory_is_entered_before_the_tui_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = tmp_path / "work"
        project.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli_main, "tui_run", lambda: None)
        assert _invoke("tui", "work").exit_code == 0
        assert Path.cwd() == project.resolve()


class TestSanitizeSession:
    def test_masks_key_named_secrets_including_plurals_and_headers(self) -> None:
        data: dict[str, Any] = {
            "openai_api_key": "placeholder",
            "tokens": ["a", "b"],
            "headers": {"X-Api-Key": "abc", "Authorization": "Bearer abcdef12345"},
            "password": 12345,
            "client_secret": "shhh",
        }
        cli_main._sanitize_session(data)
        assert data["openai_api_key"] == "***"
        assert data["tokens"] == "***"
        assert data["headers"]["X-Api-Key"] == "***"
        assert data["headers"]["Authorization"] == "***"
        assert data["password"] == "***"
        assert data["client_secret"] == "***"

    def test_masks_secret_shapes_inside_values_and_lists(self) -> None:
        data: dict[str, Any] = {
            "summary": "rotate sk-ant-AABBCCDDEEFF and ghp_AABBCCDDEEFF00112233 plus AIzaAABBCCDDEEFF0011223344",
            "messages": [{"content": "use xoxb-AABBCCDDEEFF-ww or npm_AABBCCDDEEFF0011223344556677"}],
            "env": {"AWS": "AKIAAABBCCDDEEFF0011"},
        }
        cli_main._sanitize_session(data)
        assert "sk-ant" not in data["summary"] and "***" in data["summary"]
        assert "ghp_" not in data["summary"] and "AIza" not in data["summary"]
        assert "xoxb-" not in data["messages"][0]["content"]
        assert "npm_" not in data["messages"][0]["content"]
        assert "AKIA" not in data["env"]["AWS"]

    def test_keeps_ordinary_text_and_lookalike_keys(self) -> None:
        data: dict[str, Any] = {
            "tokenizer": "cl100k_base",
            "monkey": "banana",
            "keyboard": "qwerty",
            "task": "refactor the parser",
            "steps": 4,
            "messages": [{"role": "user", "content": "risks-are-fine here"}],
        }
        cli_main._sanitize_session(data)
        assert data == {
            "tokenizer": "cl100k_base",
            "monkey": "banana",
            "keyboard": "qwerty",
            "task": "refactor the parser",
            "steps": 4,
            "messages": [{"role": "user", "content": "risks-are-fine here"}],
        }


class TestAuthCommands:
    @staticmethod
    def _with_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, creds: dict[str, Any]) -> Path:
        creds_dir = tmp_path / ".config" / "ravencode"
        creds_dir.mkdir(parents=True)
        store = creds_dir / "auth.json"
        store.write_text(json.dumps(creds), encoding="utf-8")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        return store

    def test_list_without_credentials(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert "No credentials configured" in _invoke("auth", "list").output

    def test_list_reports_configured_providers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with_creds(tmp_path, monkeypatch, {"openrouter": {"api_key": "sk-1", "base_url": "https://x"}})
        output = _invoke("auth", "list").output
        assert "openrouter:" in output
        assert "https://x" in output

    def test_logout_single_provider(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = self._with_creds(tmp_path, monkeypatch, {"a": {"api_key": "1"}, "b": {"api_key": "2"}})
        assert _invoke("auth", "logout", "a").exit_code == 0
        assert set(json.loads(store.read_text(encoding="utf-8"))) == {"b"}

    def test_logout_without_credentials(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert "No credentials to remove" in _invoke("auth", "logout").output

    def test_auth_login_prompted_key_is_stored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setattr(Path, "chmod", lambda self, mode, *a, **k: None)
        result = _invoke("auth", "login", "--provider", "groq", input="gk-secret\n")
        assert result.exit_code == 0, result.output
        creds = json.loads((tmp_path / ".config" / "ravencode" / "auth.json").read_text(encoding="utf-8"))
        assert creds["groq"]["api_key"] == "gk-secret"


class TestModelsCommand:
    def test_no_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ravencode.config.loader as loader

        monkeypatch.setattr(loader, "get_config", lambda: SimpleNamespace(resolve_providers=lambda: []))
        assert "No providers configured" in _invoke("models").output

    def test_lists_models_and_flags_missing_ones(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ravencode.config.loader as loader

        providers = [
            SimpleNamespace(name="", id="groq", models=["llama-3"], base_url="https://api.groq"),
            SimpleNamespace(name="Local", id="local", models=[], base_url=""),
        ]
        monkeypatch.setattr(loader, "get_config", lambda: SimpleNamespace(resolve_providers=lambda: providers))
        output = _invoke("models", "--verbose").output
        assert "groq" in output
        assert "- llama-3 (https://api.groq)" in output
        assert "(no models listed)" in output


class TestUpgradeCommand:
    @staticmethod
    def _fake_pip(monkeypatch: pytest.MonkeyPatch, seen: list[list[str]], returncode: int = 0) -> None:
        import subprocess

        def fake_run(cmd: list[str], **kw: Any) -> Any:
            seen.append(cmd)
            return SimpleNamespace(returncode=returncode, stderr="no network" if returncode else "")

        monkeypatch.setattr(subprocess, "run", fake_run)

    def test_upgrades_the_published_distribution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        self._fake_pip(monkeypatch, seen)
        assert _invoke("upgrade").exit_code == 0
        # the wheel ships as raven-agent; "ravencode" on PyPI is not ours
        assert seen[0][-1] == "raven-agent"

    def test_pins_the_requested_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        self._fake_pip(monkeypatch, seen)
        _invoke("upgrade", "--version", "1.2.3")
        assert seen[0][-1] == "raven-agent==1.2.3"

    def test_reports_pip_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[list[str]] = []
        self._fake_pip(monkeypatch, seen, returncode=1)
        result = _invoke("upgrade")
        assert result.exit_code == 1
        assert "no network" in result.output

    def test_reports_missing_pip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def explode(*a: Any, **k: Any) -> Any:
            raise FileNotFoundError("pip")

        monkeypatch.setattr(subprocess, "run", explode)
        result = _invoke("upgrade")
        assert result.exit_code == 1
        assert "pip not found" in result.output


class TestIntegrationCommands:
    def test_github_webhook_forwards_arguments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ravencode.integrations.github_webhook as gh_wh

        seen: dict[str, Any] = {}
        monkeypatch.setattr(gh_wh, "run_webhook_server", lambda **kw: seen.update(kw))
        _invoke("integrations", "github", "webhook", "--port", "9", "--host", "h", "--secret", "s")
        assert seen == {"host": "h", "port": 9, "token": None, "secret": "s"}

    def test_github_run_invalid_payload(self) -> None:
        result = _invoke("integrations", "github", "run", "--payload", "!!not-base64!!")
        assert result.exit_code == 1
        assert "base64" in result.output

    def test_github_run_unmatched_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_main, "parse_github_webhook", lambda name, payload: None)
        payload = base64.b64encode(b"{}").decode("ascii")
        result = _invoke("integrations", "github", "run", "--event-name", "push", "--payload", payload)
        assert "No matching event type" in result.output

    @staticmethod
    def _fake_github_integration(monkeypatch: pytest.MonkeyPatch, summary: Any) -> None:
        monkeypatch.setattr(cli_main, "parse_github_webhook", lambda name, payload: SimpleNamespace())

        class _Int:
            def __init__(self, token: str = "") -> None:
                self.token = token

            async def handle_event(self, ctx: Any) -> Any:
                return summary

        monkeypatch.setattr(cli_main, "GitHubIntegration", _Int)

    def test_github_run_reports_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_github_integration(monkeypatch, SimpleNamespace(summary="reviewed 1 PR"))
        result = _invoke(
            "integrations", "github", "run", "--event-name", "push", "--token", "gh-token", "--payload", "e30="
        )
        assert "Result: reviewed 1 PR" in result.output

    def test_github_run_without_action(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._fake_github_integration(monkeypatch, None)
        result = _invoke("integrations", "github", "run", "--event-name", "push", "--payload", "e30=")
        assert "No action taken" in result.output

    def test_github_run_reads_the_ci_env_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def parse(name: str, payload: Any) -> Any:
            seen["name"] = name
            seen["payload"] = payload
            return None

        monkeypatch.setattr(cli_main, "parse_github_webhook", parse)
        monkeypatch.setenv("RAVENCODE_GITHUB_EVENT", base64.b64encode(b'{"a": 1}').decode("ascii"))
        monkeypatch.setenv("RAVENCODE_GITHUB_EVENT_NAME", "issue_comment")
        _invoke("integrations", "github", "run")
        assert seen == {"name": "issue_comment", "payload": {"a": 1}}

    def test_gitlab_run_invalid_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RAVENCODE_GITLAB_EVENT", "{broken")
        result = _invoke("integrations", "gitlab", "run")
        assert result.exit_code == 1
        assert "invalid event payload" in result.output

    def test_gitlab_run_unmatched_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_main, "parse_gitlab_webhook", lambda name, payload: None)
        result = _invoke("integrations", "gitlab", "run")
        assert "No matching event type" in result.output

    def test_gitlab_run_reports_summary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[tuple[str, str]] = []
        monkeypatch.setattr(cli_main, "parse_gitlab_webhook", lambda name, payload: SimpleNamespace())

        class _Int:
            def __init__(self, token: str = "", api_url: str = "") -> None:
                built.append((token, api_url))

            async def handle_event(self, ctx: Any) -> Any:
                return SimpleNamespace(summary="triaged")

        monkeypatch.setattr(cli_main, "GitLabIntegration", _Int)
        result = _invoke("integrations", "gitlab", "run", "--token", "gl", "--api-url", "https://gitlab")
        assert "Result: triaged" in result.output
        assert built == [("gl", "https://gitlab")]


async def _drive_tui(
    monkeypatch: pytest.MonkeyPatch, commands: list[str], custom: dict[str, CustomCommand] | None = None
) -> str:
    buf = StringIO()
    monkeypatch.setattr(tui, "console", Console(file=buf, force_terminal=False, width=200))
    stream = iter([*commands, "/exit"])
    monkeypatch.setattr(Prompt, "ask", lambda *a, **k: next(stream))
    monkeypatch.setattr(tui, "set_question_callback", lambda cb: None)
    monkeypatch.setattr(tui, "ensure_mcp_tools", AsyncMock(side_effect=RuntimeError("mcp down")))
    monkeypatch.setattr(tui, "discover_commands", lambda: custom or {})
    await tui.main_loop()
    return buf.getvalue()


class TestTUICommandSurface:
    async def test_control_commands_report_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import ravencode.runtime.checkpoints as cps
        import ravencode.runtime.undo as undo_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(undo_mod, "undo_last", AsyncMock(return_value="undone"))
        monkeypatch.setattr(undo_mod, "redo_last", AsyncMock(return_value="redone"))
        monkeypatch.setattr(cps, "checkpoint_save", AsyncMock(return_value="saved"))
        monkeypatch.setattr(cps, "checkpoint_list", AsyncMock(return_value="none yet"))
        monkeypatch.setattr(cps, "checkpoint_restore", AsyncMock(return_value="restored"))

        out = await _drive_tui(
            monkeypatch,
            [
                "/history",
                "/undo",
                "/redo",
                "/checkpoint save before refactor",
                "/checkpoint list",
                "/checkpoint restore c1",
                "/checkpoint",
                "/save",
                "/load missing.json",
                "/nonsense",
            ],
        )
        assert "history available via MemoryStore" in out
        assert "undone" in out
        assert "redone" in out
        assert "saved" in out
        assert "none yet" in out
        assert "restored" in out
        assert "usage: /checkpoint" in out
        assert "No active session to save" in out
        assert "File not found: missing.json" in out
        assert "Unknown command: /nonsense" in out

    async def test_mcp_mode_starts_the_server(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import ravencode.mcp.server as mcp_server

        started: list[str] = []

        class _Stub:
            async def run(self) -> None:
                started.append("mcp")

        monkeypatch.setattr(mcp_server, "MCPServer", _Stub)
        out = await _drive_tui(monkeypatch, ["/mcp"])
        assert started == ["mcp"]
        assert "Starting MCP server mode" in out

    async def test_help_lists_custom_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        custom = {"ship": CustomCommand(name="ship", prompt="", description="run the release checklist")}
        out = await _drive_tui(monkeypatch, ["/help"], custom=custom)
        assert "Custom Commands" in out
        assert "run the release checklist" in out

    async def test_named_custom_command_runs_through_the_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        async def fake_delegate(task: str, **kw: Any) -> str:
            seen.append(task)
            return "shipped"

        monkeypatch.setattr(Orchestrator, "delegate", classmethod(lambda cls, task, **kw: fake_delegate(task)))
        custom = {"ship": CustomCommand(name="ship", prompt="release $ARGUMENTS", subtask=True)}
        out = await _drive_tui(monkeypatch, ["/ship v1"], custom=custom)
        assert seen == ["release v1"]
        assert "shipped" in out

    async def test_ask_then_another_ask_keeps_one_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatched: list[Any] = []

        async def fake_dispatch(self: Orchestrator, task: str, agent_type: AgentType, **kw: Any) -> Any:
            dispatched.append(kw.get("agent"))
            return SimpleNamespace(
                success=True, agent="autonomous", data={"result": f"echo {task}"}, error=None, steps=1
            )

        monkeypatch.setattr(Orchestrator, "dispatch", fake_dispatch)
        monkeypatch.setattr(Orchestrator, "new_agent", lambda self, memory_path=None: SimpleNamespace(name="live"))
        out = await _drive_tui(monkeypatch, ["/ask one", "/ask two"])
        assert len(dispatched) == 2
        assert dispatched[0] is not None
        assert dispatched[0] is dispatched[1]
        assert "echo one" in out
        assert "echo two" in out

    async def test_role_commands_route_to_their_agent_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatched: dict[str, Any] = {}

        async def fake_dispatch(self: Orchestrator, task: str, agent_type: AgentType, **kw: Any) -> Any:
            dispatched[agent_type.value] = kw.get("agent")
            return SimpleNamespace(success=True, agent=agent_type.value, data={"plan": "p"}, error=None, steps=1)

        monkeypatch.setattr(Orchestrator, "dispatch", fake_dispatch)
        await _drive_tui(monkeypatch, ["/ask keep", "/plan make a plan", "/code write it", "/debug fix it"])
        assert sorted(dispatched) == ["autonomous", "coder", "debugger", "planner"]
        # only the autonomous turn may reuse the session agent; specialists bring their own prompt
        assert dispatched["autonomous"] is not None
        assert dispatched["planner"] is None
        assert dispatched["coder"] is None
        assert dispatched["debugger"] is None

    async def test_agent_command_applies_prompt_and_tool_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        async def fake_stream(prompt: str, config: AgentConfig, system_prompt: str | None = None) -> str:
            captured["prompt"] = prompt
            captured["config"] = config
            captured["system"] = system_prompt
            return "ok"

        monkeypatch.setattr(tui, "run_streaming_agent", fake_stream)
        monkeypatch.setattr(
            tui,
            "get_custom_agents",
            lambda: {
                "reader": CustomAgentDef(
                    "reader",
                    {
                        "system_prompt": "read-only mode",
                        "tools": ["read", "grep"],
                        "max_steps": 7,
                        "confirm_dangerous": True,
                        "diff_preview": False,
                        "proactive_scan": False,
                    },
                )
            },
        )
        out = await _drive_tui(monkeypatch, ["/agent reader explain the repo", "/agent ghost do stuff"])
        assert captured["system"] == "read-only mode"
        assert captured["prompt"] == "explain the repo"
        assert captured["config"].max_steps == 7
        assert captured["config"].diff_preview is False
        permissions = captured["config"].permissions
        assert permissions is not None
        assert permissions.is_allowed("read")[0] is True
        assert permissions.is_allowed("grep")[0] is True
        assert permissions.is_allowed("write")[0] is False
        assert "Unknown agent: ghost" in out


class TestCustomCommandDispatch:
    async def test_subtask_commands_delegate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        async def fake_delegate(task: str) -> str:
            seen.append(task)
            return "delegated"

        monkeypatch.setattr(Orchestrator, "delegate", classmethod(lambda cls, task, **kw: fake_delegate(task)))
        cmd = CustomCommand(name="ship", prompt="prompt:$ARGUMENTS", subtask=True)
        await tui.run_custom_command(cmd, "v1")
        assert seen == ["prompt:v1"]

    async def test_agent_commands_route_by_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[tuple[str, Any]] = []

        async def fake_run_agent(task: str, agent_type: AgentType = AgentType.AUTONOMOUS) -> None:
            called.append((task, agent_type))

        monkeypatch.setattr(tui, "run_agent", fake_run_agent)
        await tui.run_custom_command(CustomCommand(name="fix", prompt="p", agent="debugger"), "")
        assert called == [("p", AgentType.DEBUGGER)]

    async def test_unknown_role_falls_back_to_autonomous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[Any] = []

        async def fake_run_agent(task: str, agent_type: AgentType = AgentType.AUTONOMOUS) -> None:
            called.append(agent_type)

        monkeypatch.setattr(tui, "run_agent", fake_run_agent)
        await tui.run_custom_command(CustomCommand(name="x", prompt="p", agent="ghost"), "")
        assert called == [AgentType.AUTONOMOUS]

    async def test_plain_commands_stream(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        async def fake_stream(prompt: str, config: AgentConfig, system_prompt: str | None = None) -> str:
            called.append(prompt)
            return "ok"

        monkeypatch.setattr(tui, "run_streaming_agent", fake_stream)
        await tui.run_custom_command(CustomCommand(name="q", prompt="ask me"), "")
        assert called == ["ask me"]
