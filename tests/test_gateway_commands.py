from __future__ import annotations

from typing import Any

import pytest

from raven.core.auth.models import Permission, Role
from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage
from tests.conftest import MockChannel


@pytest.fixture
def gateway_with_perms(gateway: Gateway) -> Gateway:
    for role in Role:
        for perm in Permission:
            gateway._rbac.add_role_permission(role, perm)
    return gateway


@pytest.fixture
def user() -> dict[str, Any]:
    return {"id": "U1", "name": "Test User", "role": "user"}


def _event(text: str, channel: str = "mock") -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        user_id="U1",
        session_id=f"{channel}:C1:default",
        text=text,
        metadata={},
    )


class TestBasicCommands:
    async def test_new_command(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/new"), user)
        assert result is True

    async def test_new_command_clears_default_session(self, gateway: Gateway, user: dict[str, Any]):
        from raven.core.models import Message

        await gateway.start()
        sid = "mock:C1:default"
        await gateway.db.get_or_create_session(sid, "mock", "U1")
        await gateway.db.save_message(Message(session_id=sid, role="user", content="hello"))
        await gateway._handle_command(_event("/new"), user)
        msgs = await gateway.db.get_session_messages(sid)
        assert not msgs

    async def test_reset_command_clears_default_session(self, gateway: Gateway, user: dict[str, Any]):
        from raven.core.models import Message

        await gateway.start()
        sid = "mock:C1:default"
        await gateway.db.get_or_create_session(sid, "mock", "U1")
        await gateway.db.save_message(Message(session_id=sid, role="user", content="hello"))
        await gateway._handle_command(_event("/reset"), user)
        msgs = await gateway.db.get_session_messages(sid)
        assert not msgs

    async def test_think_command_stores_pref(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/think high"), user)
        assert result is True
        assert gateway.get_pref("mock", "U1", "think_level") == "high"

    async def test_think_command_invalid_usage(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/think insane"), user)
        assert result is True
        assert gateway.get_pref("mock", "U1", "think_level", "high") == "high"

    async def test_verbose_command_stores_pref(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/verbose on"), user)
        assert result is True
        assert gateway.get_pref("mock", "U1", "verbose") == "on"

    async def test_activation_command_stores_pref(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/activation always"), user)
        assert result is True
        assert gateway.get_pref("mock", "U1", "activation_mode") == "always"

    async def test_help_command(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/help"), user)
        assert result is True

    async def test_unknown_command(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/nonexistent"), user)
        assert result is not True


class TestMonitorCommands:
    async def test_monitor_list(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor list"), user)
        assert result is True

    async def test_monitor_add(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor add http http://example.com"), user)
        assert result is True

    async def test_monitor_remove(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor remove 1"), user)
        assert result is True

    async def test_monitor_pause(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor pause 1"), user)
        assert result is True

    async def test_monitor_resume(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor resume 1"), user)
        assert result is True


class TestRoutineCommands:
    async def test_routine_list(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine list"), user)
        assert result is True

    async def test_routine_add(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine add send_briefing '0 9 * * *'"), user)
        assert result is True

    async def test_routine_add_unquoted_cron(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine add send_briefing 0 9 * * *"), user)
        assert result is True
        routines = await gateway_with_perms._routine_store.list_routines(user_id="U1")
        assert routines
        assert routines[0].schedule == "0 9 * * *"

    async def test_routine_add_cron_with_name(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(
            _event("/routine add send_briefing */30 9-18 * * 1-5 brief"), user
        )
        assert result is True
        routines = await gateway_with_perms._routine_store.list_routines(user_id="U1")
        assert routines
        assert routines[0].schedule == "*/30 9-18 * * 1-5"
        assert routines[0].name == "brief"

    async def test_routine_add_invalid_schedule_rejected(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine add send_briefing 5.5"), user)
        assert result is True
        routines = await gateway_with_perms._routine_store.list_routines(user_id="U1")
        assert routines == []

    async def test_routine_add_zero_interval_rejected(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine add send_briefing 0"), user)
        assert result is True
        routines = await gateway_with_perms._routine_store.list_routines(user_id="U1")
        assert routines == []


class TestTaskCommands:
    async def test_task_command_routes(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/task do something"), user)
        assert result is True

    async def test_task_list(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/task list"), user)
        assert result is True


class TestCodeCommands:
    async def test_code_index(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        result = await gateway_with_perms._handle_command(_event("/code index"), user)
        assert result is True

    async def test_code_search(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        result = await gateway_with_perms._handle_command(_event("/code search test"), user)
        assert result is True

    async def test_code_review(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        result = await gateway_with_perms._handle_command(_event("/code review test.py"), user)
        assert result is True

    async def test_code_index_denied_outside_workspace(
        self, gateway_with_perms: Gateway, user: dict[str, Any], monkeypatch, tmp_path
    ):
        from raven.core.config import settings

        ws = tmp_path / "ws"
        ws.mkdir()
        monkeypatch.setattr(settings, "workspace_path", str(ws))
        sent: list[tuple[str, str]] = []

        async def fake_send(channel_id: str, session_id: str, text: str, streaming: bool = False):
            sent.append((channel_id, text))

        gateway_with_perms._send = fake_send  # type: ignore[method-assign]
        result = await gateway_with_perms._handle_command(
            _event(f"/code index {tmp_path / 'outside'}"), user
        )
        assert result is True
        assert any("Access denied" in text for _, text in sent)

    async def test_code_review_denied_prefix_sibling(
        self, gateway_with_perms: Gateway, user: dict[str, Any], monkeypatch, tmp_path
    ):
        from raven.core.config import settings

        ws = tmp_path / "ws"
        ws.mkdir()
        evil = tmp_path / "ws_evil"
        evil.mkdir()
        secret = evil / "secret.py"
        secret.write_text("password = 'hunter2'\n", encoding="utf-8")
        monkeypatch.setattr(settings, "workspace_path", str(ws))
        sent: list[tuple[str, str]] = []

        async def fake_send(channel_id: str, session_id: str, text: str, streaming: bool = False):
            sent.append((channel_id, text))

        gateway_with_perms._send = fake_send  # type: ignore[method-assign]
        result = await gateway_with_perms._handle_command(
            _event(f"/code review {secret!s}"), user
        )
        assert result is True
        assert any("Access denied" in text for _, text in sent)

    async def test_code_review_allowed_inside_workspace(
        self, gateway_with_perms: Gateway, user: dict[str, Any], monkeypatch, tmp_path
    ):
        from raven.core.config import settings

        ws = tmp_path / "ws"
        ws.mkdir()
        target = ws / "ok.py"
        target.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(settings, "workspace_path", str(ws))
        sent: list[tuple[str, str]] = []

        async def fake_send(channel_id: str, session_id: str, text: str, streaming: bool = False):
            sent.append((channel_id, text))

        gateway_with_perms._send = fake_send  # type: ignore[method-assign]
        result = await gateway_with_perms._handle_command(_event(f"/code review {target!s}"), user)
        assert result is True
        assert not any("Access denied" in text for _, text in sent)


class TestVoiceCommands:
    async def test_voice_tts(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/voice tts hello"), user)
        assert result is True


class TestCleanText:
    async def test_clean_text_strips_mention(self, gateway: Gateway):
        result = gateway._clean_text("discord", "<@12345> hello")
        assert "hello" in result

    async def test_clean_text_no_mention(self, gateway: Gateway):
        result = gateway._clean_text("telegram", "hello world")
        assert result == "hello world"
