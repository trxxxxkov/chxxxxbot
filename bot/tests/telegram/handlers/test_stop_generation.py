"""Tests for stop_generation handler.

Tests the /stop command handler and cancel_if_active helper.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from aiogram import types
import pytest


class TestHandleStopCommand:
    """Tests for handle_stop_command handler."""

    @pytest.fixture
    def mock_message(self) -> MagicMock:
        """Create a mock Message for /stop command."""
        message = MagicMock(spec=types.Message)
        message.text = "/stop"
        message.from_user = MagicMock()
        message.from_user.id = 456
        message.chat = MagicMock()
        message.chat.id = 123
        return message

    @pytest.mark.asyncio
    async def test_stop_command_cancels_generation(
            self, mock_message: MagicMock) -> None:
        """Test that /stop command cancels active generation silently."""
        from telegram.generation_tracker import generation_tracker
        from telegram.handlers.stop_generation import handle_stop_command

        # Start a generation
        await generation_tracker.start(chat_id=123, user_id=456)

        await handle_stop_command(mock_message)

        # Generation should be cancelled (event set)
        assert not generation_tracker.is_active(123, 456)

        # Cleanup
        await generation_tracker.cleanup(123, 456)

    @pytest.mark.asyncio
    async def test_stop_command_no_active_generation(
            self, mock_message: MagicMock) -> None:
        """Test that /stop works silently when no active generation."""
        from telegram.handlers.stop_generation import handle_stop_command

        # Should not raise
        await handle_stop_command(mock_message)

    @pytest.mark.asyncio
    async def test_stop_command_missing_from_user(
            self, mock_message: MagicMock) -> None:
        """Test handling of missing from_user."""
        from telegram.handlers.stop_generation import handle_stop_command

        mock_message.from_user = None

        # Should return early, not crash
        await handle_stop_command(mock_message)

    @pytest.mark.asyncio
    async def test_stop_command_missing_chat(self,
                                             mock_message: MagicMock) -> None:
        """Test handling of missing chat."""
        from telegram.handlers.stop_generation import handle_stop_command

        mock_message.chat = None

        # Should return early, not crash
        await handle_stop_command(mock_message)


class TestCancelIfActive:
    """Tests for cancel_if_active function."""

    @pytest.mark.asyncio
    async def test_cancel_if_active_returns_true_when_active(self) -> None:
        """Test that cancel_if_active returns True when generation active."""
        from telegram.generation_tracker import generation_tracker
        from telegram.handlers.stop_generation import cancel_if_active

        await generation_tracker.start(chat_id=123, user_id=456)

        result = await cancel_if_active(chat_id=123, user_id=456)

        assert result is True

        # Cleanup
        await generation_tracker.cleanup(123, 456)

    @pytest.mark.asyncio
    async def test_cancel_if_active_returns_false_when_not_active(self) -> None:
        """Test that cancel_if_active returns False when no generation."""
        from telegram.handlers.stop_generation import cancel_if_active

        result = await cancel_if_active(chat_id=123, user_id=456)

        assert result is False
