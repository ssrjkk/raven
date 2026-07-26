from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.channels.discord.channel import HAS_DISCORD, DiscordChannel
from raven.core.models import IncomingMessage


@pytest.fixture
def channel():
    return DiscordChannel()


class TestRegisterSlashCommands:
    @pytest.mark.asyncio
    async def test_slash_commands_registered_when_deps_present(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        mock_tree = MagicMock()
        mock_tree.command = MagicMock()
        channel._tree = mock_tree
        channel._register_slash_commands()
        assert mock_tree.command.call_count == 4


class TestSlashCommandIntegration:
    @pytest.mark.asyncio
    async def test_all_four_slash_commands_capture(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        captured = {}
        mock_tree = MagicMock()

        def capture_decorator(*args, **kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn
            return wrapper

        mock_tree.command = capture_decorator
        channel._tree = mock_tree
        channel._register_slash_commands()
        assert "slash_task" in captured
        assert "slash_monitor" in captured
        assert "slash_code" in captured
        assert "slash_routine" in captured

    @pytest.mark.asyncio
    async def test_slash_task_handler(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        captured = {}
        mock_tree = MagicMock()

        def capture_decorator(*args, **kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn
            return wrapper

        mock_tree.command = capture_decorator
        channel._tree = mock_tree
        channel._register_slash_commands()

        handler = AsyncMock()
        channel._handler = handler

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.id = 100
        interaction.user.__str__ = MagicMock(return_value="testuser")
        interaction.channel.id = 12345
        interaction.channel.__str__ = MagicMock(return_value="test-channel")

        await captured["slash_task"](interaction, goal="build something")
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert isinstance(event, IncomingMessage)
        assert "/task build something" in event.text
        interaction.followup.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_slash_monitor_handler(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        captured = {}
        mock_tree = MagicMock()

        def capture_decorator(*args, **kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn
            return wrapper

        mock_tree.command = capture_decorator
        channel._tree = mock_tree
        channel._register_slash_commands()

        handler = AsyncMock()
        channel._handler = handler

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.id = 100
        interaction.user.__str__ = MagicMock(return_value="testuser")
        interaction.channel.id = 12345
        interaction.channel.__str__ = MagicMock(return_value="test-channel")

        await captured["slash_monitor"](interaction, action="list", target="")
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert "/monitor list" in event.text

    @pytest.mark.asyncio
    async def test_slash_code_handler(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        captured = {}
        mock_tree = MagicMock()

        def capture_decorator(*args, **kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn
            return wrapper

        mock_tree.command = capture_decorator
        channel._tree = mock_tree
        channel._register_slash_commands()

        handler = AsyncMock()
        channel._handler = handler

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.id = 100
        interaction.user.__str__ = MagicMock(return_value="testuser")
        interaction.channel.id = 12345
        interaction.channel.__str__ = MagicMock(return_value="test-channel")

        await captured["slash_code"](interaction, action="review", arg="main.py")
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert "/code review main.py" in event.text

    @pytest.mark.asyncio
    async def test_slash_routine_handler(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        captured = {}
        mock_tree = MagicMock()

        def capture_decorator(*args, **kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn
            return wrapper

        mock_tree.command = capture_decorator
        channel._tree = mock_tree
        channel._register_slash_commands()

        handler = AsyncMock()
        channel._handler = handler

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.id = 100
        interaction.user.__str__ = MagicMock(return_value="testuser")
        interaction.channel.id = 12345
        interaction.channel.__str__ = MagicMock(return_value="test-channel")

        await captured["slash_routine"](interaction, action="list", args="")
        handler.assert_awaited_once()
        event = handler.call_args[0][0]
        assert "/routine list" in event.text

    @pytest.mark.asyncio
    async def test_slash_task_no_handler(self, channel):
        if not HAS_DISCORD:
            pytest.skip("discord.py not installed")
        captured = {}
        mock_tree = MagicMock()

        def capture_decorator(*args, **kwargs):
            def wrapper(fn):
                captured[fn.__name__] = fn
                return fn
            return wrapper

        mock_tree.command = capture_decorator
        channel._tree = mock_tree
        channel._register_slash_commands()

        channel._handler = None

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.user.id = 100
        interaction.user.__str__ = MagicMock(return_value="testuser")
        interaction.channel.id = 12345
        interaction.channel.__str__ = MagicMock(return_value="test-channel")

        await captured["slash_task"](interaction, goal="test")
        interaction.followup.send.assert_awaited_once()


class TestPrefixCommands:
    @pytest.mark.asyncio
    async def test_start_no_discord(self, channel):
        with patch("raven.channels.discord.channel.HAS_DISCORD", False):
            await channel.start()
            assert not channel._ready

    @pytest.mark.asyncio
    async def test_start_no_token(self, channel):
        with patch("raven.channels.discord.channel.HAS_DISCORD", True), patch.object(channel, "_token", None):
            await channel.start()
            assert not channel._ready
