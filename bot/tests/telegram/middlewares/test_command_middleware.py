"""Tests for CommandMiddleware and CallbackLoggingMiddleware.

Tests topic registration for commands and callback logging.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from aiogram import types
import pytest
from telegram.middlewares.command_middleware import CallbackLoggingMiddleware
from telegram.middlewares.command_middleware import CommandMiddleware


@pytest.fixture
def mock_message():
    """Create a mock Telegram message."""
    message = MagicMock(spec=types.Message)
    message.text = "/start"
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.from_user.is_bot = False
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.from_user.username = "testuser"
    message.from_user.language_code = "en"
    message.from_user.is_premium = False
    message.from_user.added_to_attachment_menu = False
    message.from_user.allows_users_to_create_topics = False
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.message_thread_id = None
    message.message_id = 100
    return message


@pytest.fixture
def mock_message_with_topic():
    """Create a mock Telegram message in a topic."""
    message = MagicMock(spec=types.Message)
    message.text = "/help"
    message.from_user = MagicMock()
    message.from_user.id = 123456789
    message.from_user.is_bot = False
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.from_user.username = "testuser"
    message.from_user.language_code = "en"
    message.from_user.is_premium = False
    message.from_user.added_to_attachment_menu = False
    message.from_user.allows_users_to_create_topics = False
    message.chat = MagicMock()
    message.chat.id = 123456789
    message.message_thread_id = 12345  # Topic ID
    message.message_id = 101
    return message


@pytest.fixture
def mock_session():
    """Create a mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_handler():
    """Create a mock handler."""
    handler = AsyncMock()
    handler.return_value = None
    return handler


class TestCommandMiddleware:
    """Tests for CommandMiddleware."""

    @pytest.mark.asyncio
    async def test_non_command_passes_through(self, mock_message, mock_handler,
                                              mock_session):
        """Non-command messages should pass through without registration."""
        mock_message.text = "Hello, world!"  # Not a command
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        await middleware(mock_handler, mock_message, data)

        mock_handler.assert_called_once_with(mock_message, data)

    @pytest.mark.asyncio
    async def test_command_without_topic_passes_through(self, mock_message,
                                                        mock_handler,
                                                        mock_session):
        """Commands in General (no topic) should pass through without registration."""
        mock_message.text = "/start"
        mock_message.message_thread_id = None  # General
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        with patch.object(middleware,
                          "_ensure_topic_registered",
                          new_callable=AsyncMock) as mock_register:
            await middleware(mock_handler, mock_message, data)

            # Should NOT call _ensure_topic_registered (no topic_id)
            mock_register.assert_not_called()
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_in_topic_registers_topic(self,
                                                    mock_message_with_topic,
                                                    mock_handler, mock_session):
        """Commands in a topic should trigger topic registration."""
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        with patch.object(middleware,
                          "_ensure_topic_registered",
                          new_callable=AsyncMock) as mock_register:
            await middleware(mock_handler, mock_message_with_topic, data)

            # Should call _ensure_topic_registered
            mock_register.assert_called_once_with(
                session=mock_session,
                event=mock_message_with_topic,
                chat_id=123456789,
                user_id=123456789,
                topic_id=12345,
            )
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_command_with_bot_username_suffix(self,
                                                    mock_message_with_topic,
                                                    mock_handler, mock_session):
        """Commands with @bot_username suffix should be parsed correctly."""
        mock_message_with_topic.text = "/help@mybot"
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        with patch("telegram.middlewares.command_middleware.logger"
                  ) as mock_logger:
            with patch.object(middleware,
                              "_ensure_topic_registered",
                              new_callable=AsyncMock):
                await middleware(mock_handler, mock_message_with_topic, data)

                # Check that command name was extracted correctly
                mock_logger.info.assert_called()
                call_kwargs = mock_logger.info.call_args[1]
                assert call_kwargs["command"] == "help"

    @pytest.mark.asyncio
    async def test_command_with_args(self, mock_message_with_topic,
                                     mock_handler, mock_session):
        """Commands with arguments should be logged with args."""
        mock_message_with_topic.text = "/topup @user 10.50"
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        with patch("telegram.middlewares.command_middleware.logger"
                  ) as mock_logger:
            with patch.object(middleware,
                              "_ensure_topic_registered",
                              new_callable=AsyncMock):
                await middleware(mock_handler, mock_message_with_topic, data)

                call_kwargs = mock_logger.info.call_args[1]
                assert call_kwargs["command"] == "topup"
                assert call_kwargs["args"] == "@user 10.50"

    @pytest.mark.asyncio
    async def test_ensure_topic_registered_creates_records(self, mock_session):
        """_ensure_topic_registered should create user, chat, and thread."""
        middleware = CommandMiddleware()

        mock_message = MagicMock()
        mock_message.from_user = MagicMock()
        mock_message.from_user.id = 123456789
        mock_message.from_user.is_bot = False
        mock_message.from_user.first_name = "Test"
        mock_message.from_user.last_name = None
        mock_message.from_user.username = "testuser"
        mock_message.from_user.language_code = "en"
        mock_message.from_user.is_premium = False
        mock_message.from_user.added_to_attachment_menu = False
        mock_message.from_user.allows_users_to_create_topics = False

        with patch("telegram.middlewares.command_middleware.UserRepository"
                  ) as MockUserRepo:
            with patch("telegram.middlewares.command_middleware.ChatRepository"
                      ) as MockChatRepo:
                with patch(
                        "telegram.middlewares.command_middleware.ThreadRepository"
                ) as MockThreadRepo:
                    # Setup mocks
                    mock_user_repo = MockUserRepo.return_value
                    mock_user_repo.get_by_telegram_id = AsyncMock(
                        return_value=None)
                    mock_user_repo.get_or_create = AsyncMock(
                        return_value=(MagicMock(), True))

                    mock_chat_repo = MockChatRepo.return_value
                    mock_chat_repo.get_or_create = AsyncMock(
                        return_value=(MagicMock(), True))

                    mock_thread_repo = MockThreadRepo.return_value
                    mock_thread_repo.get_or_create_thread = AsyncMock(
                        return_value=(MagicMock(id=1), True))

                    result = await middleware._ensure_topic_registered(
                        session=mock_session,
                        event=mock_message,
                        chat_id=123456789,
                        user_id=123456789,
                        topic_id=12345,
                    )

                    # Verify all repos were called
                    mock_user_repo.get_by_telegram_id.assert_called_once()
                    mock_chat_repo.get_or_create.assert_called_once()
                    mock_thread_repo.get_or_create_thread.assert_called_once()
                    mock_session.commit.assert_called_once()

                    # Should return True since thread was created
                    assert result is True

    @pytest.mark.asyncio
    async def test_ensure_topic_registered_handles_errors(self, mock_session):
        """_ensure_topic_registered should not fail command on errors."""
        middleware = CommandMiddleware()

        mock_message = MagicMock()
        mock_message.from_user = MagicMock()

        with patch("telegram.middlewares.command_middleware.UserRepository"
                  ) as MockUserRepo:
            mock_user_repo = MockUserRepo.return_value
            mock_user_repo.get_by_telegram_id = AsyncMock(
                side_effect=Exception("DB error"))

            with patch("telegram.middlewares.command_middleware.logger"
                      ) as mock_logger:
                # Should not raise exception
                result = await middleware._ensure_topic_registered(
                    session=mock_session,
                    event=mock_message,
                    chat_id=123456789,
                    user_id=123456789,
                    topic_id=12345,
                )

                # Should log info (external error, gracefully handled)
                mock_logger.info.assert_called()
                call_args = mock_logger.info.call_args
                assert "topic_registration_failed" in call_args[0][0]

                # Should return False on error
                assert result is False

    @pytest.mark.asyncio
    async def test_topic_was_created_flag_passed_to_handler(
            self, mock_message_with_topic, mock_handler, mock_session):
        """topic_was_created flag should be passed to handler via data."""
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        with patch.object(middleware,
                          "_ensure_topic_registered",
                          new_callable=AsyncMock,
                          return_value=True) as mock_register:
            await middleware(mock_handler, mock_message_with_topic, data)

            # Verify flag is passed in data
            mock_handler.assert_called_once()
            call_data = mock_handler.call_args[0][1]
            assert "topic_was_created" in call_data
            assert call_data["topic_was_created"] is True

    @pytest.mark.asyncio
    async def test_topic_was_created_false_for_existing_topic(
            self, mock_message_with_topic, mock_handler, mock_session):
        """topic_was_created should be False for existing topics."""
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        with patch.object(middleware,
                          "_ensure_topic_registered",
                          new_callable=AsyncMock,
                          return_value=False):
            await middleware(mock_handler, mock_message_with_topic, data)

            call_data = mock_handler.call_args[0][1]
            assert call_data["topic_was_created"] is False

    @pytest.mark.asyncio
    async def test_topic_was_created_false_without_topic(
            self, mock_message, mock_handler, mock_session):
        """topic_was_created should be False when no topic (General)."""
        mock_message.text = "/help"
        middleware = CommandMiddleware()
        data = {"session": mock_session}

        await middleware(mock_handler, mock_message, data)

        call_data = mock_handler.call_args[0][1]
        assert call_data["topic_was_created"] is False


class TestCallbackLoggingMiddleware:
    """Tests for CallbackLoggingMiddleware."""

    @pytest.fixture
    def mock_callback_query(self):
        """Create a mock callback query."""
        query = MagicMock(spec=types.CallbackQuery)
        query.from_user = MagicMock()
        query.from_user.id = 123456789
        query.message = MagicMock()
        query.message.chat = MagicMock()
        query.message.chat.id = 123456789
        query.data = "action:value"
        query.id = "callback_123"
        return query

    @pytest.mark.asyncio
    async def test_callback_logging(self, mock_callback_query, mock_handler):
        """Callback queries should be logged."""
        middleware = CallbackLoggingMiddleware()
        data = {}

        with patch("telegram.middlewares.command_middleware.logger"
                  ) as mock_logger:
            await middleware(mock_handler, mock_callback_query, data)

            mock_logger.info.assert_called()
            call_kwargs = mock_logger.info.call_args[1]
            assert call_kwargs["action"] == "action"
            assert call_kwargs["callback_data"] == "action:value"
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_without_colon(self, mock_callback_query,
                                          mock_handler):
        """Callback data without colon should use full data as action."""
        mock_callback_query.data = "simple_action"
        middleware = CallbackLoggingMiddleware()
        data = {}

        with patch("telegram.middlewares.command_middleware.logger"
                  ) as mock_logger:
            await middleware(mock_handler, mock_callback_query, data)

            call_kwargs = mock_logger.info.call_args[1]
            assert call_kwargs["action"] == "simple_action"
