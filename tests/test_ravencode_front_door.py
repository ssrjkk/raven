"""Front-door tests for ravencode: server auth, safe session import, TUI session continuity."""

from __future__ import annotations

import base64
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner
from fastapi import HTTPException
from rich.prompt import Prompt

from raven.core.config import settings
from ravencode.agents.custom_agents import CustomAgentDef
from ravencode.agents.orchestrator import AgentType, Orchestrator
from ravencode.api import server as srv
from ravencode.cli import main as cli_main
from ravencode.cli import tui
from ravencode.runtime import agent_core as agent_mod
from ravencode.runtime.agent_core import AgentConfig, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.session import SessionStore


@pytest.fixture(autouse=True)
def _isolate_last_agent() -> Iterator[None]:
    token = agent_mod._last_agent_var.set(None)
    yield
    agent_mod._last_agent_var.reset(token)


def _basic(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")


class _FakeUvicorn:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(self, app: Any, **kwargs: Any) -> None:
        self.calls.append(kwargs)


@pytest.fixture()
def fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> _FakeUvicorn:
    fake = _FakeUvicorn()
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=fake.run))
    return fake


@pytest.fixture()
def no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "_API_KEY", "")
    monkeypatch.setattr(srv, "_BASIC_PASSWORD", "")
    monkeypatch.setattr(srv, "_BASIC_USERNAME", "ravencode")


class TestServeCredentialsAreWired:
    def test_serve_forwards_username_and_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(srv, "run_openai_server", lambda **kw: seen.update(kw))
        result = CliRunner().invoke(
            cli_main.cli, ["serve", "--host", "0.0.0.0", "--port", "9000", "--username", "u", "--password", "pw"]
        )
        assert result.exit_code == 0, result.output
        assert seen == {"host": "0.0.0.0", "port": 9000, "username": "u", "password": "pw"}

    def test_serve_falls_back_to_env_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}
        monkeypatch.setattr(srv, "run_openai_server", lambda **kw: seen.update(kw))
        monkeypatch.setenv("RAVENCODE_SERVER_PASSWORD", "from-env")
        CliRunner().invoke(cli_main.cli, ["serve"])
        assert seen["password"] == "from-env"

    def test_web_command_no_longer_promises_a_ui(self) -> None:
        result = CliRunner().invoke(cli_main.cli, ["web"])
        assert result.exit_code != 0
        assert "No such command" in result.output


class TestRunOpenaiServerBindGuard:
    def test_public_bind_without_auth_is_refused(self, fake_uvicorn: _FakeUvicorn, no_auth: None) -> None:
        with pytest.raises(RuntimeError, match="without authentication"):
            srv.run_openai_server(host="0.0.0.0", port=8080)
        assert fake_uvicorn.calls == []

    def test_public_bind_with_password_is_allowed(self, fake_uvicorn: _FakeUvicorn, no_auth: None) -> None:
        srv.run_openai_server(host="0.0.0.0", port=8080, username="u", password="hunter2")
        assert fake_uvicorn.calls[0]["host"] == "0.0.0.0"
        srv._check_auth(_basic("u", "hunter2"))
        with pytest.raises(HTTPException):
            srv._check_auth(_basic("u", "wrong"))

    def test_loopback_bind_without_auth_still_runs(self, fake_uvicorn: _FakeUvicorn, no_auth: None) -> None:
        srv.run_openai_server(host="127.0.0.1", port=8080)
        assert fake_uvicorn.calls[0]["port"] == 8080


class TestCheckAuth:
    def test_open_when_nothing_configured(self, no_auth: None) -> None:
        srv._check_auth("")

    def test_bearer_api_key_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_API_KEY", "sk-1")
        srv._check_auth("Bearer sk-1")

    def test_raw_api_key_accepted_for_back_compat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_API_KEY", "sk-1")
        srv._check_auth("sk-1")

    def test_wrong_api_key_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_API_KEY", "sk-1")
        with pytest.raises(HTTPException):
            srv._check_auth("Bearer nope")

    def test_basic_credentials_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_BASIC_PASSWORD", "pw")
        monkeypatch.setattr(srv, "_BASIC_USERNAME", "ravencode")
        srv._check_auth(_basic("ravencode", "pw"))

    def test_basic_wrong_username_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_BASIC_PASSWORD", "pw")
        monkeypatch.setattr(srv, "_BASIC_USERNAME", "ravencode")
        with pytest.raises(HTTPException):
            srv._check_auth(_basic("admin", "pw"))

    def test_malformed_basic_header_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_BASIC_PASSWORD", "pw")
        with pytest.raises(HTTPException):
            srv._check_auth("Basic not!base64!at!all")

    def test_missing_password_part_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(srv, "_BASIC_PASSWORD", "pw")
        with pytest.raises(HTTPException):
            srv._check_auth("Basic " + base64.b64encode(b"user-only").decode("ascii"))


class TestSessionImportIsSSRRProtected:
    def test_import_goes_through_the_ssrf_guard(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import raven.core.security.ssrf as ssrf

        seen: list[str] = []

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"id": "s1", "steps": 3}

        async def fake_fetch(url: str, **kw: Any) -> _Resp:
            seen.append(url)
            return _Resp()

        monkeypatch.setattr(ssrf, "safe_fetch_async", fake_fetch)
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "data" / "raven.db"))
        result = CliRunner().invoke(cli_main.cli, ["session", "import", "https://example.com/s.json"])
        assert result.exit_code == 0, result.output
        assert seen == ["https://example.com/s.json"]
        assert (tmp_path / "data" / "sessions" / "s1.json").is_file()

    def test_private_address_is_blocked_without_network(self) -> None:
        import raven.core.security.ssrf as ssrf

        assert ssrf.is_private_url("http://127.0.0.1:9/x.json") is True
        result = CliRunner().invoke(cli_main.cli, ["session", "import", "http://127.0.0.1:9/x.json"])
        assert result.exit_code == 1
        assert "Failed to fetch URL" in result.output
        assert "private IP" in result.output

    def test_local_file_import_still_works(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "data" / "raven.db"))
        share = tmp_path / "share.json"
        share.write_text(json.dumps({"id": "abc"}), encoding="utf-8")
        result = CliRunner().invoke(cli_main.cli, ["session", "import", str(share)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "data" / "sessions" / "abc.json").is_file()


class TestCredentialFilePermissions:
    def test_save_creds_restricts_to_owner(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        chmods: list[tuple[Path, int]] = []

        def fake_chmod(self: Path, mode: int, *a: Any, **k: Any) -> None:
            chmods.append((self, mode))

        monkeypatch.setattr(Path, "chmod", fake_chmod)
        target = tmp_path / "auth.json"
        cli_main._save_creds(target, {"openrouter": {"api_key": "sk-1"}})
        assert chmods == [(target, 0o600)]
        assert json.loads(target.read_text(encoding="utf-8"))["openrouter"]["api_key"] == "sk-1"

    def test_auth_login_writes_key_and_locks_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        chmods: list[int] = []

        def fake_chmod(self: Path, mode: int, *a: Any, **k: Any) -> None:
            chmods.append(mode)

        monkeypatch.setattr(Path, "chmod", fake_chmod)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = CliRunner().invoke(cli_main.cli, ["auth", "login", "--provider", "openrouter", "--key", "sk-abc"])
        assert result.exit_code == 0, result.output
        creds = json.loads((tmp_path / ".config" / "ravencode" / "auth.json").read_text(encoding="utf-8"))
        assert creds["openrouter"]["api_key"] == "sk-abc"
        assert 0o600 in chmods


class TestSessionResumeIsLive:
    def test_load_state_adopts_the_agent_as_live(self) -> None:
        state = {
            "name": "raven",
            "config": {},
            "conversation": [
                {"role": "system", "content": "s"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "yo"},
            ],
        }
        agent = ReActAgent.load_state(state)
        assert ReActAgent.last_agent() is agent
        assert agent.conversation.message_count == 2

    async def test_store_load_adopts_the_agent(self, tmp_path: Path) -> None:
        store = SessionStore(storage_dir=str(tmp_path))
        agent = ReActAgent(
            config=AgentConfig(),
            conversation=Conversation(
                system_prompt="s",
                messages=[{"role": "user", "content": "earlier turn"}],
            ),
        )
        session_id = await store.save(agent, "round")

        loaded = await store.load(session_id)
        assert loaded is not None
        assert ReActAgent.last_agent() is loaded
        assert any("earlier turn" in json.dumps(m) for m in loaded.conversation.messages)

    async def test_dispatch_reuses_the_live_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        live = ReActAgent(config=AgentConfig(), conversation=Conversation(system_prompt="s"))
        ran: list[str] = []

        async def fake_run(task: str, *a: Any, **k: Any) -> str:
            ran.append(task)
            return "fine"

        monkeypatch.setattr(live, "run", fake_run)

        def explode(*a: Any, **k: Any) -> Any:
            raise AssertionError("a live agent must not trigger a rebuild")

        monkeypatch.setattr(Orchestrator, "_build_with_override", explode)
        result = await Orchestrator().dispatch("hello", AgentType.AUTONOMOUS, agent=live)
        assert ran == ["hello"]
        assert result.success and result.data == {"result": "fine"}

    async def test_specialists_ignore_the_live_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        built: list[Any] = []

        class _Stub:
            conversation = SimpleNamespace(message_count=1)

            async def run(self, task: str) -> str:
                return "planned"

        def build(*a: Any, **k: Any) -> Any:
            stub = _Stub()
            built.append(stub)
            return stub

        monkeypatch.setattr(Orchestrator, "_build_with_override", build)
        live = ReActAgent(config=AgentConfig(), conversation=Conversation(system_prompt="s"))
        result = await Orchestrator().dispatch("t", AgentType.PLANNER, agent=live)
        assert len(built) == 1
        assert result.data == {"plan": "planned"}


class TestTUIContinuity:
    async def test_ask_reuses_one_session_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub: Any = SimpleNamespace(name="stub")
        dispatched: list[Any] = []

        async def fake_dispatch(
            self: Orchestrator,
            task: str,
            agent_type: AgentType,
            memory_path: str | None = None,
            agent_config_override: AgentConfig | None = None,
            agent: Any = None,
        ) -> Any:
            dispatched.append(agent)
            return SimpleNamespace(
                success=True, agent="autonomous", data={"result": "ok"}, error=None, steps=1
            )

        monkeypatch.setattr(tui, "_session_agent", None)
        monkeypatch.setattr(Orchestrator, "dispatch", fake_dispatch)
        monkeypatch.setattr(Orchestrator, "new_agent", lambda self, memory_path=None: stub)

        await tui.run_agent("first")
        await tui.run_agent("second")
        assert dispatched == [stub, stub]
        assert tui._session_agent is stub

    async def test_role_switch_does_not_touch_the_session_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub: Any = SimpleNamespace(name="stub")
        dispatched: list[Any] = []

        async def fake_dispatch(self: Orchestrator, task: str, agent_type: AgentType, **kw: Any) -> Any:
            dispatched.append(kw.get("agent"))
            return SimpleNamespace(success=True, agent="planner", data={"plan": "p"}, error=None, steps=0)

        monkeypatch.setattr(tui, "_session_agent", stub)
        monkeypatch.setattr(Orchestrator, "dispatch", fake_dispatch)
        await tui.run_agent("plan this", AgentType.PLANNER)
        assert dispatched == [None]
        assert tui._session_agent is stub

    async def test_run_streaming_agent_applies_the_custom_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        class _Stub:
            def __init__(self, config: Any = None, conversation: Any = None, **kw: Any) -> None:
                captured["conversation"] = conversation

            async def run(self, task: str) -> str:
                return "answer"

        monkeypatch.setattr(tui, "ReActAgent", _Stub)
        out = await tui.run_streaming_agent("hi", AgentConfig(), system_prompt="you are a poet")
        assert out == "answer"
        conv = captured["conversation"]
        assert conv is not None
        assert conv.messages[0]["content"] == "you are a poet"

    async def test_run_streaming_agent_without_prompt_keeps_the_default_build(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        class _Stub:
            def __init__(self, config: Any = None, conversation: Any = None, **kw: Any) -> None:
                captured["conversation"] = conversation

            async def run(self, task: str) -> str:
                return "answer"

        monkeypatch.setattr(tui, "ReActAgent", _Stub)
        await tui.run_streaming_agent("hi", AgentConfig())
        assert captured["conversation"] is None

    async def test_load_adopts_the_session_and_survives_a_corrupt_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        good = tmp_path / "good.json"
        good.write_text(
            json.dumps(
                {
                    "name": "raven",
                    "config": {},
                    "conversation": [
                        {"role": "system", "content": "s"},
                        {"role": "user", "content": "remember me"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        bad = tmp_path / "bad.json"
        bad.write_text("{definitely not json", encoding="utf-8")

        commands = iter([f"/load {bad}", f"/load {good}", "/exit"])
        monkeypatch.setattr(tui, "_session_agent", None)
        monkeypatch.setattr(Prompt, "ask", lambda *a, **k: next(commands))
        monkeypatch.setattr(tui, "set_question_callback", lambda cb: None)
        monkeypatch.setattr(tui, "ensure_mcp_tools", AsyncMock(side_effect=RuntimeError("mcp down")))
        monkeypatch.setattr(tui, "discover_commands", lambda: {})

        await tui.main_loop()
        assert tui._session_agent is not None
        assert tui._session_agent.conversation.message_count == 1
        assert any("remember me" in json.dumps(m) for m in tui._session_agent.conversation.messages)


class TestCustomAgentPolicy:
    def test_no_policy_means_no_manager(self) -> None:
        assert tui._agent_permissions(CustomAgentDef("plain", {})) is None

    def test_restricted_tools_are_denied(self) -> None:
        pm = tui._agent_permissions(CustomAgentDef("safe", {"restricted_tools": ["bash", "git_commit"]}))
        assert pm is not None
        assert pm.is_allowed("bash")[0] is False
        assert pm.is_allowed("read")[0] is True

    def test_tool_allowlist_denies_everything_else(self) -> None:
        pm = tui._agent_permissions(CustomAgentDef("reader", {"tools": ["read", "grep", "glob"]}))
        assert pm is not None
        assert pm.is_allowed("read")[0] is True
        assert pm.is_allowed("grep")[0] is True
        assert pm.is_allowed("write")[0] is False
        assert pm.is_allowed("bash")[0] is False


class TestCIWorkflowInstall:
    def test_github_install_writes_the_workflow(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli_main.cli, ["integrations", "github", "install"])
            assert result.exit_code == 0, result.output
            target = Path(".github/workflows/ravencode.yml")
            assert target.is_file()
            body = target.read_text(encoding="utf-8")
            assert "ravencode integrations github run" in body

            again = runner.invoke(cli_main.cli, ["integrations", "github", "install"])
            assert again.exit_code == 1
            assert "already exists" in again.output

            forced = runner.invoke(cli_main.cli, ["integrations", "github", "install", "--force"])
            assert forced.exit_code == 0

    def test_github_workflow_is_parseable_and_least_privilege(self) -> None:
        import yaml

        raw = yaml.safe_load(Path("ravencode/integrations/github_workflow.yml").read_text(encoding="utf-8"))
        triggers = raw.get("on", raw.get(True))
        assert "issue_comment" in triggers
        assert raw["permissions"]["contents"] == "read"
        assert "issues" in raw["permissions"]
        job = raw["jobs"]["ravencode"]
        assert job["runs-on"] == "ubuntu-latest"
        assert any("github run" in step.get("run", "") for step in job["steps"])

    def test_gitlab_install_writes_a_file_the_include_can_find(self) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli_main.cli, ["integrations", "gitlab", "install"])
            assert result.exit_code == 0, result.output
            target = Path(".gitlab-ci-ravencode.yml")
            assert target.is_file()
            assert 'local: ".gitlab-ci-ravencode.yml"' in result.output

    def test_shipped_templates_exist_next_to_the_cli(self) -> None:
        integrations = Path(cli_main.__file__).resolve().parent.parent / "integrations"
        assert (integrations / "github_workflow.yml").is_file()
        assert (integrations / "gitlab_ci.yml").is_file()
