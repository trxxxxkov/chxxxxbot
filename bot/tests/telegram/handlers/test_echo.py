"""Tests for echo message handler.

This module contains comprehensive tests for telegram/handlers/echo.py,
testing the catch-all echo handler with mocked Telegram objects.

NO __init__.py - use direct import:
    pytest tests/telegram/handlers/test_echo.py
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.handlers.echo import echo_handler


@pytest.fixture
def mock_message():
    """Create mock Telegram Message object.

    Returns:
        Mock Message with text and answer method.
    """
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.text = "Hello, bot!"
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_echo_handler_basic_text(mock_message):
    """Test echo handler with normal text message.

    Verifies that message is echoed back with prefix.

    Args:
        mock_message: Mock Telegram message.
    """
    with patch('telegram.handlers.echo.logger'):
        await echo_handler(mock_message)

        # Verify echo response
        mock_message.answer.assert_called_once_with("You said: Hello, bot!")


@pytest.mark.asyncio
async def test_echo_handler_empty_text():
    """Test echo handler with empty text.

    Verifies handling of empty string (should still work).
    """
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.text = ""
    message.answer = AsyncMock()

    with patch('telegram.handlers.echo.logger'):
        await echo_handler(message)

        message.answer.assert_called_once_with("You said: ")


@pytest.mark.asyncio
async def test_echo_handler_long_text():
    """Test echo handler with long text message.

    Verifies that long messages are handled correctly.
    """
    long_text = "A" * 1000
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.text = long_text
    message.answer = AsyncMock()

    with patch('telegram.handlers.echo.logger'):
        await echo_handler(message)

        expected = f"You said: {long_text}"
        message.answer.assert_called_once_with(expected)


@pytest.mark.asyncio
async def test_echo_handler_special_characters():
    """Test echo handler with special characters.

    Verifies handling of emoji, unicode, HTML entities.
    """
    special_text = "Hello 👋 <b>World</b> & 你好"
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.text = special_text
    message.answer = AsyncMock()

    with patch('telegram.handlers.echo.logger'):
        await echo_handler(message)

        expected = f"You said: {special_text}"
        message.answer.assert_called_once_with(expected)


@pytest.mark.asyncio
async def test_echo_handler_missing_from_user():
    """Test echo handler when from_user is None.

    Verifies graceful handling (logs with user_id=None).
    """
    message = AsyncMock()
    message.from_user = None
    message.text = "Anonymous message"
    message.answer = AsyncMock()

    with patch('telegram.handlers.echo.logger') as mock_logger:
        await echo_handler(message)

        # Should log with user_id=None
        mock_logger.info.assert_called_once()
        call_kwargs = mock_logger.info.call_args[1]
        assert call_kwargs['user_id'] is None

        # Should still echo
        message.answer.assert_called_once_with("You said: Anonymous message")


@pytest.mark.asyncio
async def test_echo_handler_logging(mock_message):
    """Test that echo handler logs message information.

    Verifies structured logging with user_id and text_length.

    Args:
        mock_message: Mock Telegram message.
    """
    with patch('telegram.handlers.echo.logger') as mock_logger:
        await echo_handler(mock_message)

        # Verify logging
        mock_logger.info.assert_called_once_with(
            "echo_message",
            user_id=mock_message.from_user.id,
            text_length=len(mock_message.text),
        )


@pytest.mark.asyncio
async def test_echo_handler_filter_text_only():
    """Test that echo handler is registered with F.text filter.

    Verifies that handler only processes text messages (not photos, etc).
    This test documents the expected filter configuration.
    """
    from aiogram import F
    from telegram.handlers.echo import router

    # Check router name
    assert router.name == "echo"

    # Handler should be registered
    # (actual filter verification would require aiogram internals testing)
    # This test documents that F.text filter is used
    handlers = router.message.handlers
    assert len(handlers) > 0


@pytest.mark.asyncio
async def test_echo_handler_none_text():
    """Test echo handler when text is None.

    Verifies handling of unexpected None value.
    """
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.text = None
    message.answer = AsyncMock()

    with patch('telegram.handlers.echo.logger') as mock_logger:
        await echo_handler(message)

        # Should log text_length=0 for None
        call_kwargs = mock_logger.info.call_args[1]
        assert call_kwargs['text_length'] == 0

        # Should echo None (f-string converts to "None")
        message.answer.assert_called_once_with("You said: None")


@pytest.mark.asyncio
async def test_echo_handler_multiline_text():
    """Test echo handler with multiline text.

    Verifies that newlines are preserved in echo.
    """
    multiline = "Line 1\nLine 2\nLine 3"
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.text = multiline
    message.answer = AsyncMock()

    with patch('telegram.handlers.echo.logger'):
        await echo_handler(message)

        expected = f"You said: {multiline}"
        message.answer.assert_called_once_with(expected)
        # Verify newlines preserved
        assert "\n" in message.answer.call_args[0][0]
