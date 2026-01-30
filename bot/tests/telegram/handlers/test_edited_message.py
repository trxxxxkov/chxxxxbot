"""Tests for telegram/handlers/edited_message.py.

Tests the edited message handler for tracking message edits.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


class TestHandleEditedMessage:
    """Tests for handle_edited_message function."""

    @pytest.fixture
    def mock_message(self):
        """Create mock Telegram message."""
        message = MagicMock()
        message.chat.id = 123456
        message.message_id = 789
        message.from_user = MagicMock()
        message.from_user.id = 111
        message.text = "Edited text content"
        message.caption = None
        message.edit_date = datetime(2024,
                                     1,
                                     15,
                                     12,
                                     30,
                                     0,
                                     tzinfo=timezone.utc)
        return message

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_edit_updates_message_in_database(
        self,
        mock_message,
        mock_session,
    ):
        """Test that edited message updates the database."""
        from telegram.handlers.edited_message import handle_edited_message

        # Mock the repository
        mock_repo = MagicMock()
        mock_updated_msg = MagicMock()
        mock_updated_msg.edit_count = 1
        mock_updated_msg.original_content = "Original text"
        mock_repo.update_message_edit = AsyncMock(return_value=mock_updated_msg)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ):
            await handle_edited_message(mock_message, mock_session)

        # Verify repository called correctly
        mock_repo.update_message_edit.assert_called_once_with(
            chat_id=123456,
            message_id=789,
            text_content="Edited text content",
            caption=None,
            edit_date=int(mock_message.edit_date.timestamp()),
        )

    @pytest.mark.asyncio
    async def test_edit_with_caption_instead_of_text(
        self,
        mock_message,
        mock_session,
    ):
        """Test editing a message with caption (media)."""
        from telegram.handlers.edited_message import handle_edited_message

        mock_message.text = None
        mock_message.caption = "Edited caption"

        mock_repo = MagicMock()
        mock_updated_msg = MagicMock()
        mock_updated_msg.edit_count = 2
        mock_updated_msg.original_content = "Original caption"
        mock_repo.update_message_edit = AsyncMock(return_value=mock_updated_msg)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ):
            await handle_edited_message(mock_message, mock_session)

        mock_repo.update_message_edit.assert_called_once_with(
            chat_id=123456,
            message_id=789,
            text_content=None,
            caption="Edited caption",
            edit_date=int(mock_message.edit_date.timestamp()),
        )

    @pytest.mark.asyncio
    async def test_edit_message_not_found(
        self,
        mock_message,
        mock_session,
    ):
        """Test handling edit for message not in database."""
        from telegram.handlers.edited_message import handle_edited_message

        mock_repo = MagicMock()
        mock_repo.update_message_edit = AsyncMock(return_value=None)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ), patch("telegram.handlers.edited_message.logger") as mock_logger:
            await handle_edited_message(mock_message, mock_session)

        # Should log debug for not found
        mock_logger.debug.assert_called()
        call_args = mock_logger.debug.call_args
        assert "edited_message.not_found" in str(call_args)

    @pytest.mark.asyncio
    async def test_edit_logs_successful_update(
        self,
        mock_message,
        mock_session,
    ):
        """Test that successful edit is logged."""
        from telegram.handlers.edited_message import handle_edited_message

        mock_repo = MagicMock()
        mock_updated_msg = MagicMock()
        mock_updated_msg.edit_count = 3
        mock_updated_msg.original_content = "First version"
        mock_repo.update_message_edit = AsyncMock(return_value=mock_updated_msg)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ), patch("telegram.handlers.edited_message.logger") as mock_logger:
            await handle_edited_message(mock_message, mock_session)

        # Check info log for successful update
        mock_logger.info.assert_called()
        # Find the update log call
        update_calls = [
            c for c in mock_logger.info.call_args_list
            if "edited_message.updated" in str(c)
        ]
        assert len(update_calls) == 1

    @pytest.mark.asyncio
    async def test_edit_without_from_user(
        self,
        mock_message,
        mock_session,
    ):
        """Test edit from channel (no from_user)."""
        from telegram.handlers.edited_message import handle_edited_message

        mock_message.from_user = None

        mock_repo = MagicMock()
        mock_updated_msg = MagicMock()
        mock_updated_msg.edit_count = 1
        mock_updated_msg.original_content = None
        mock_repo.update_message_edit = AsyncMock(return_value=mock_updated_msg)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ), patch("telegram.handlers.edited_message.logger") as mock_logger:
            await handle_edited_message(mock_message, mock_session)

        # Should still work, just log None for user_id
        mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_edit_without_edit_date(
        self,
        mock_message,
        mock_session,
    ):
        """Test edit without edit_date (shouldn't happen but handle gracefully)."""
        from telegram.handlers.edited_message import handle_edited_message

        mock_message.edit_date = None

        mock_repo = MagicMock()
        mock_updated_msg = MagicMock()
        mock_updated_msg.edit_count = 1
        mock_updated_msg.original_content = None
        mock_repo.update_message_edit = AsyncMock(return_value=mock_updated_msg)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ):
            await handle_edited_message(mock_message, mock_session)

        mock_repo.update_message_edit.assert_called_once_with(
            chat_id=123456,
            message_id=789,
            text_content="Edited text content",
            caption=None,
            edit_date=None,
        )

    @pytest.mark.asyncio
    async def test_edit_with_int_edit_date(
        self,
        mock_message,
        mock_session,
    ):
        """Test edit with int edit_date (Unix timestamp).

        In some aiogram versions or contexts, edit_date may be an int
        (Unix timestamp) instead of datetime object.
        """
        from telegram.handlers.edited_message import handle_edited_message

        # edit_date as Unix timestamp (int) instead of datetime
        mock_message.edit_date = 1705321800  # 2024-01-15 12:30:00 UTC

        mock_repo = MagicMock()
        mock_updated_msg = MagicMock()
        mock_updated_msg.edit_count = 1
        mock_updated_msg.original_content = None
        mock_repo.update_message_edit = AsyncMock(return_value=mock_updated_msg)

        with patch(
                "telegram.handlers.edited_message.MessageRepository",
                return_value=mock_repo,
        ):
            await handle_edited_message(mock_message, mock_session)

        mock_repo.update_message_edit.assert_called_once_with(
            chat_id=123456,
            message_id=789,
            text_content="Edited text content",
            caption=None,
            edit_date=1705321800,
        )


class TestEditedMessageRouter:
    """Tests for edited_message router configuration."""

    def test_router_name(self):
        """Test router has correct name."""
        from telegram.handlers.edited_message import router

        assert router.name == "edited_message"

    def test_router_has_edited_message_handler(self):
        """Test router has edited_message handler registered."""
        from telegram.handlers.edited_message import router

        # Check that there are observers for edited_message
        assert len(router.edited_message.handlers) > 0
