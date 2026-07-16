# mypy: ignore-errors
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage


@pytest.fixture
def gateway():
    gw = Gateway.__new__(Gateway)
    gw.db = MagicMock()
    gw.db.get_or_create_session = AsyncMock(return_value=MagicMock(id="test_sid"))
    gw.db.find_or_create_user = AsyncMock(return_value=MagicMock())
    gw.db.get_session_messages = AsyncMock(return_value=[])
    gw.db.save_message = AsyncMock()
    gw.db.get_user = AsyncMock(return_value=MagicMock())
    gw.db.delete_session = AsyncMock()
    gw.db.get_plugin_state = AsyncMock(return_value=None)
    gw.db.save_plugin_state = AsyncMock()
    gw.llm = MagicMock()
    gw.llm.chat = AsyncMock(return_value=MagicMock(content="Hello!", tool_calls=[]))
    gw.failover = MagicMock()
    gw.failover.complete = AsyncMock(return_value="test response")
    gw.plugin_loader = MagicMock()
    gw.plugin_loader.tools = []
    gw.registry = MagicMock()
    gw.registry.plugins = {}
    from raven.core.gateway.channel_manager import ChannelManager
    gw.channels = ChannelManager()
    tel = AsyncMock()
    tel.channel_id = "telegram"
    web = AsyncMock()
    web.channel_id = "webchat"
    gw.channels.register(tel)
    gw.channels.register(web)
    gw.sandbox = None  # type: ignore[assignment]
    gw._monitor_engine = MagicMock()
    gw._routine_engine = MagicMock()  # type: ignore[attr-defined]
    gw._task_runner = MagicMock()  # type: ignore[attr-defined]
    gw._skills = {}  # type: ignore[attr-defined]
    gw._plugins_loaded = False  # type: ignore[attr-defined]
    from raven.core.auth.models import Permission, Role
    from raven.core.auth.rbac import RBAC
    gw._rbac = RBAC()
    for role in Role:
        for perm in Permission:
            gw._rbac.add_role_permission(role, perm)
    from raven.core.channel_guardian import ChannelGuardian
    gw._guardian = MagicMock(spec=ChannelGuardian)
    gw._guardian.record_error = AsyncMock()
    gw._guardian.record_success = AsyncMock()
    gw._bg_tasks = set()
    return gw


def _event(text: str, channel: str = "telegram") -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        user_id="U1",
        session_id=f"{channel}:C1:default",
        text=text,
        metadata={},
    )


@pytest.fixture
def user() -> dict:
    return {"id": "U1", "name": "Test User"}


class TestGatewayCommandHandler:
    @pytest.mark.asyncio
    async def test_new_command(self, gateway, user):
        result = await gateway._handle_command(_event("/new"), user)
        assert result is True

    @pytest.mark.asyncio
    async def test_reset_command(self, gateway, user):
        result = await gateway._handle_command(_event("/reset"), user)
        assert result is True

    @pytest.mark.asyncio
    async def test_help_command(self, gateway, user):
        result = await gateway._handle_command(_event("/help"), user)
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_command(self, gateway, user):
        with patch.object(gateway, "_send", new_callable=AsyncMock):
            result = await gateway._handle_command(_event("/nonexistent"), user)
            assert result is not True


class TestGatewayMonitorCommands:
    @pytest.mark.asyncio
    async def test_monitor_list(self, gateway, user):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor list"
            result = await gateway._handle_command(_event("/monitor list"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_add(self, gateway, user):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor added"
            result = await gateway._handle_command(_event("/monitor add http https://example.com"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_remove(self, gateway, user):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor removed"
            result = await gateway._handle_command(_event("/monitor remove 1"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_pause(self, gateway, user):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor paused"
            result = await gateway._handle_command(_event("/monitor pause 1"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_resume(self, gateway, user):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor resumed"
            result = await gateway._handle_command(_event("/monitor resume 1"), user)
            assert result is True


class TestGatewayRoutineCommands:
    @pytest.mark.asyncio
    async def test_routine_list(self, gateway, user):
        with patch.object(gateway, "_handle_routine_cmd") as mock_cmd:
            mock_cmd.return_value = "Routine list"
            result = await gateway._handle_command(_event("/routine list"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_routine_add(self, gateway, user):
        with patch.object(gateway, "_handle_routine_cmd") as mock_cmd:
            mock_cmd.return_value = "Routine added"
            result = await gateway._handle_command(_event("/routine add briefing 0 9 * * *"), user)
            assert result is True


class TestGatewayTaskCommands:
    @pytest.mark.asyncio
    async def test_task_command_routes(self, gateway, user):
        with patch.object(gateway, "_run_task", new_callable=AsyncMock):
            with patch.object(gateway, "_send", new_callable=AsyncMock):
                result = await gateway._handle_command(_event("/task do something"), user)
                assert result is True

    @pytest.mark.asyncio
    async def test_task_list(self, gateway, user):
        with patch.object(gateway, "_send", new_callable=AsyncMock):
            result = await gateway._handle_command(_event("/task list"), user)
            assert result is True


class TestGatewayCodeCommands:
    @pytest.mark.asyncio
    async def test_code_index(self, gateway, user):
        with patch.object(gateway, "_handle_code_cmd") as mock_cmd:
            mock_cmd.return_value = "Indexed"
            result = await gateway._handle_command(_event("/code index"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_code_search(self, gateway, user):
        with patch.object(gateway, "_handle_code_cmd") as mock_cmd:
            mock_cmd.return_value = "Search results"
            result = await gateway._handle_command(_event("/code search test"), user)
            assert result is True

    @pytest.mark.asyncio
    async def test_code_review(self, gateway, user):
        with patch.object(gateway, "_handle_code_cmd") as mock_cmd:
            mock_cmd.return_value = "Review"
            result = await gateway._handle_command(_event("/code review test.py"), user)
            assert result is True


class TestGatewayVoiceCommands:
    @pytest.mark.asyncio
    async def test_voice_tts(self, gateway, user):
        with patch.object(gateway, "_handle_voice_cmd") as mock_cmd:
            mock_cmd.return_value = "Playing TTS"
            result = await gateway._handle_command(_event("/voice tts hello"), user)
            assert result is True


class TestGatewayCleanText:
    def test_clean_text_strips_mention(self, gateway):
        result = gateway._clean_text("discord", "<@12345> hello")
        assert "hello" in result

    def test_clean_text_no_mention(self, gateway):
        result = gateway._clean_text("telegram", "hello world")
        assert result == "hello world"
