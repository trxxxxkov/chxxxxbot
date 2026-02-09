"""Tests for start and help command handlers.

This module contains comprehensive tests for telegram/handlers/start.py,
testing /start and /help command handlers with mocked Telegram objects.

NO __init__.py - use direct import:
    pytest tests/telegram/handlers/test_start.py
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.handlers.start import help_handler
from telegram.handlers.start import start_handler


@pytest.fixture
def mock_message():
    """Create mock Telegram Message object.

    Returns:
        Mock Message with from_user, answer method.
    """
    message = AsyncMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.from_user.is_bot = False
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.from_user.username = "testuser"
    message.from_user.language_code = "en"
    message.from_user.is_premium = False
    message.from_user.added_to_attachment_menu = False
    message.answer = AsyncMock()
    return message


@pytest.fixture
def mock_session():
    """Create mock AsyncSession.

    Returns:
        Mock session for database operations.
    """
    return AsyncMock()


@pytest.fixture
def mock_user_repo():
    """Create mock UserRepository.

    Returns:
        Mock UserRepository with get_or_create method.
    """
    repo = MagicMock()
    repo.get_or_create = AsyncMock()
    return repo


@pytest.mark.asyncio
async def test_start_handler_new_user(mock_message, mock_session):
    """Test /start handler with new user.

    Verifies that new users get 'Welcome!' greeting.

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.UserRepository') as mock_repo_class:
        mock_repo = MagicMock()
        mock_user = MagicMock()
        mock_repo.get_or_create = AsyncMock(return_value=(mock_user, True))
        mock_repo_class.return_value = mock_repo

        await start_handler(mock_message, mock_session)

        # Verify UserRepository called correctly
        mock_repo_class.assert_called_once_with(mock_session)
        mock_repo.get_or_create.assert_called_once()

        # Verify greeting for new user
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "👋 Welcome!" in call_args
        assert "I'm an LLM bot" in call_args


@pytest.mark.asyncio
async def test_start_handler_existing_user(mock_message, mock_session):
    """Test /start handler with existing user.

    Verifies that returning users get 'Welcome back!' greeting.

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.UserRepository') as mock_repo_class:
        mock_repo = MagicMock()
        mock_user = MagicMock()
        mock_repo.get_or_create = AsyncMock(return_value=(mock_user, False))
        mock_repo_class.return_value = mock_repo

        await start_handler(mock_message, mock_session)

        # Verify greeting for returning user
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "👋 Welcome back!" in call_args


@pytest.mark.asyncio
async def test_start_handler_missing_from_user(mock_session):
    """Test /start handler when from_user is None.

    Verifies proper error handling for anonymous messages.

    Args:
        mock_session: Mock database session.
    """
    message = AsyncMock()
    message.from_user = None
    message.answer = AsyncMock()

    await start_handler(message, mock_session)

    # Should send error message
    message.answer.assert_called_once_with("⚠️ Unable to identify user.")


@pytest.mark.asyncio
async def test_start_handler_database_error(mock_message, mock_session):
    """Test /start handler with database error.

    Verifies that exceptions are propagated (middleware handles them).

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.UserRepository') as mock_repo_class:
        mock_repo = MagicMock()
        mock_repo.get_or_create = AsyncMock(
            side_effect=Exception("Database error"))
        mock_repo_class.return_value = mock_repo

        # Exception should propagate (middleware handles it)
        with pytest.raises(Exception, match="Database error"):
            await start_handler(mock_message, mock_session)


@pytest.mark.asyncio
async def test_start_handler_session_injection(mock_message):
    """Test that start_handler receives session from middleware.

    Verifies dependency injection pattern.

    Args:
        mock_message: Mock Telegram message.
    """
    mock_session = AsyncMock()

    with patch('telegram.handlers.start.UserRepository') as mock_repo_class:
        mock_repo = MagicMock()
        mock_repo.get_or_create = AsyncMock(return_value=(MagicMock(), True))
        mock_repo_class.return_value = mock_repo

        await start_handler(mock_message, mock_session)

        # Verify session passed to UserRepository
        mock_repo_class.assert_called_once_with(mock_session)


@pytest.mark.asyncio
async def test_start_handler_logging(mock_message, mock_session):
    """Test that start_handler logs user information.

    Verifies structured logging with user context.

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.UserRepository') as mock_repo_class, \
         patch('telegram.handlers.start.logger') as mock_logger:

        mock_repo = MagicMock()
        mock_repo.get_or_create = AsyncMock(return_value=(MagicMock(), True))
        mock_repo_class.return_value = mock_repo

        await start_handler(mock_message, mock_session)

        # Verify logging (1 call: start_command)
        # Note: user.new_user_joined is logged in UserRepository, not here
        assert mock_logger.info.call_count == 1
        mock_logger.info.assert_called_once_with(
            "start_command",
            user_id=mock_message.from_user.id,
            username=mock_message.from_user.username,
            was_created=True,
        )


@pytest.mark.asyncio
async def test_help_handler_basic(mock_message, mock_session):
    """Test /help handler sends help message.

    Verifies help text content and HTML formatting.

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.logger'), \
         patch('telegram.handlers.start.config') as mock_config:
        mock_config.PRIVILEGED_USERS = set()

        await help_handler(mock_message, mock_session)

        # Verify help message sent
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args

        # Check content
        message_text = call_args[0][0]
        assert "Help" in message_text
        assert "/start" in message_text
        assert "/help" in message_text

        # Check HTML format
        assert call_args[1]['parse_mode'] == "HTML"


@pytest.mark.asyncio
async def test_help_handler_message_format(mock_message, mock_session):
    """Test help message format and structure.

    Verifies that help message contains all required sections.

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.logger'), \
         patch('telegram.handlers.start.config') as mock_config:
        mock_config.PRIVILEGED_USERS = set()

        await help_handler(mock_message, mock_session)

        message_text = mock_message.answer.call_args[0][0]

        # Required sections
        assert "/model" in message_text
        assert "/pay" in message_text
        assert "/balance" in message_text


@pytest.mark.asyncio
async def test_help_handler_logging(mock_message, mock_session):
    """Test that help_handler logs request.

    Verifies logging of help command usage.

    Args:
        mock_message: Mock Telegram message.
        mock_session: Mock database session.
    """
    with patch('telegram.handlers.start.logger') as mock_logger, \
         patch('telegram.handlers.start.config') as mock_config:
        mock_config.PRIVILEGED_USERS = set()

        await help_handler(mock_message, mock_session)

        # Verify logging
        mock_logger.info.assert_called_once_with(
            "help_command",
            user_id=mock_message.from_user.id,
        )


@pytest.mark.asyncio
async def test_help_handler_no_from_user(mock_session):
    """Test help_handler when from_user is None.

    Verifies graceful handling of anonymous requests.
    """
    message = AsyncMock()
    message.from_user = None
    message.answer = AsyncMock()

    with patch('telegram.handlers.start.logger') as mock_logger, \
         patch('telegram.handlers.start.config') as mock_config:
        mock_config.PRIVILEGED_USERS = set()

        await help_handler(message, mock_session)

        # Should log with user_id=None
        mock_logger.info.assert_called_once_with(
            "help_command",
            user_id=None,
        )

        # Should still send help message
        message.answer.assert_called_once()
