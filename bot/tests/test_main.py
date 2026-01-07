"""Tests for application entry point.

This module contains comprehensive tests for main.py, testing
application startup, secret reading, initialization sequence, error
handling, and cleanup.

NO __init__.py - use direct import:
    pytest tests/test_main.py
"""

from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch

from main import main
from main import read_secret
import pytest


def test_read_secret_valid_file(tmp_path):
    """Test read_secret with valid secret file.

    Verifies reading from /run/secrets/ directory.

    Args:
        tmp_path: pytest fixture providing temporary directory.
    """
    secret_content = "test_secret_value_123"

    with patch('main.Path') as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.read_text.return_value = secret_content

        result = read_secret("test_secret")

        # Verify path construction
        mock_path.assert_called_once_with("/run/secrets/test_secret")

        # Verify file reading
        mock_instance.read_text.assert_called_once_with(encoding='utf-8')

        # Verify result
        assert result == secret_content


def test_read_secret_missing_file():
    """Test read_secret when file doesn't exist.

    Verifies FileNotFoundError is raised.
    """
    with patch('main.Path') as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.read_text.side_effect = FileNotFoundError(
            "Secret file not found")

        with pytest.raises(FileNotFoundError):
            read_secret("missing_secret")


def test_read_secret_strips_whitespace():
    """Test that read_secret strips whitespace.

    Verifies trailing newlines and spaces are removed.
    """
    secret_with_whitespace = "  secret_value  \n\n"

    with patch('main.Path') as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.read_text.return_value = secret_with_whitespace

        result = read_secret("test_secret")

        # Should be stripped
        assert result == "secret_value"
        assert "\n" not in result


@pytest.mark.asyncio
async def test_main_startup_success():
    """Test successful main() startup sequence.

    Verifies all initialization steps execute in correct order.
    """
    with patch('main.setup_logging') as mock_setup_logging, \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url') as mock_get_db_url, \
         patch('main.init_db') as mock_init_db, \
         patch('main.read_secret') as mock_read_secret, \
         patch('main.create_bot') as mock_create_bot, \
         patch('main.create_dispatcher') as mock_create_dispatcher, \
         patch('main.dispose_db') as mock_dispose_db:

        # Setup mocks
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_get_db_url.return_value = "postgresql://test"
        mock_read_secret.return_value = "test_bot_token"
        mock_bot = MagicMock()
        mock_create_bot.return_value = mock_bot
        mock_dispatcher = MagicMock()
        mock_dispatcher.start_polling = AsyncMock()
        mock_create_dispatcher.return_value = mock_dispatcher
        mock_dispose_db.return_value = AsyncMock()()

        await main()

        # Verify initialization sequence
        mock_setup_logging.assert_called_once_with(level="INFO")
        mock_get_db_url.assert_called_once()
        mock_init_db.assert_called_once_with("postgresql://test", echo=False)
        mock_read_secret.assert_called_once_with("telegram_bot_token")
        mock_create_bot.assert_called_once_with(token="test_bot_token")
        mock_create_dispatcher.assert_called_once()
        mock_dispatcher.start_polling.assert_called_once_with(mock_bot)

        # Verify cleanup
        mock_dispose_db.assert_called_once()


@pytest.mark.asyncio
async def test_main_missing_bot_token():
    """Test main() when telegram_bot_token secret is missing.

    Verifies FileNotFoundError handling and cleanup.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url'), \
         patch('main.init_db'), \
         patch('main.read_secret') as mock_read_secret, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_read_secret.side_effect = FileNotFoundError(
            "telegram_bot_token not found")
        mock_dispose_db.return_value = AsyncMock()()

        # Should raise FileNotFoundError
        with pytest.raises(FileNotFoundError):
            await main()

        # Verify error logged
        mock_logger.error.assert_called()
        error_call = [
            c for c in mock_logger.error.call_args_list
            if c[0][0] == "secret_not_found"
        ]
        assert len(error_call) > 0

        # Verify cleanup still called
        mock_dispose_db.assert_called_once()


@pytest.mark.asyncio
async def test_main_missing_postgres_password():
    """Test main() when postgres_password secret is missing.

    Verifies error handling in get_database_url().
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url') as mock_get_db_url, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_get_db_url.side_effect = FileNotFoundError(
            "postgres_password not found")
        mock_dispose_db.return_value = AsyncMock()()

        # Should propagate FileNotFoundError
        with pytest.raises(FileNotFoundError):
            await main()

        # Verify cleanup
        mock_dispose_db.assert_called_once()


@pytest.mark.asyncio
async def test_main_database_init_failure():
    """Test main() when database initialization fails.

    Verifies error handling and cleanup.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url'), \
         patch('main.init_db') as mock_init_db, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_init_db.side_effect = Exception("Database connection failed")
        mock_dispose_db.return_value = AsyncMock()()

        # Should propagate exception
        with pytest.raises(Exception, match="Database connection failed"):
            await main()

        # Verify error logged
        error_calls = [
            c for c in mock_logger.error.call_args_list
            if c[0][0] == "startup_error"
        ]
        assert len(error_calls) > 0

        # Verify cleanup
        mock_dispose_db.assert_called_once()


@pytest.mark.asyncio
async def test_main_invalid_bot_token():
    """Test main() with invalid bot token format.

    Verifies error handling when creating bot with bad token.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url'), \
         patch('main.init_db'), \
         patch('main.read_secret') as mock_read_secret, \
         patch('main.create_bot') as mock_create_bot, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_read_secret.return_value = "invalid_token"
        mock_create_bot.side_effect = Exception("Invalid token format")
        mock_dispose_db.return_value = AsyncMock()()

        # Should propagate exception
        with pytest.raises(Exception, match="Invalid token format"):
            await main()

        # Verify cleanup
        mock_dispose_db.assert_called_once()


@pytest.mark.asyncio
async def test_main_cleanup_on_error():
    """Test that cleanup happens even on errors.

    Verifies dispose_db() called in finally block.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url') as mock_get_db_url, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_get_db_url.side_effect = RuntimeError("Unexpected error")
        mock_dispose_db.return_value = AsyncMock()()

        # Error should propagate
        with pytest.raises(RuntimeError):
            await main()

        # Cleanup MUST be called
        mock_dispose_db.assert_called_once()

        # bot_stopped should be logged
        stop_calls = [
            c for c in mock_logger.info.call_args_list
            if c[0][0] == "bot_stopped"
        ]
        assert len(stop_calls) > 0


@pytest.mark.asyncio
async def test_main_finally_block_always_runs():
    """Test that finally block executes in all scenarios.

    Verifies cleanup regardless of success or failure.
    """
    # Test 1: Success scenario
    with patch('main.setup_logging'), \
         patch('main.get_logger'), \
         patch('main.get_database_url'), \
         patch('main.init_db'), \
         patch('main.read_secret'), \
         patch('main.create_bot'), \
         patch('main.create_dispatcher') as mock_create_dispatcher, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_dispatcher = MagicMock()
        mock_dispatcher.start_polling = AsyncMock()
        mock_create_dispatcher.return_value = mock_dispatcher
        mock_dispose_db.return_value = AsyncMock()()

        await main()

        # Cleanup called on success
        assert mock_dispose_db.call_count == 1

    # Test 2: Error scenario
    with patch('main.setup_logging'), \
         patch('main.get_logger'), \
         patch('main.get_database_url') as mock_get_db_url, \
         patch('main.dispose_db') as mock_dispose_db:

        mock_get_db_url.side_effect = Exception("Error")
        mock_dispose_db.return_value = AsyncMock()()

        with pytest.raises(Exception):
            await main()

        # Cleanup called on error
        assert mock_dispose_db.call_count == 1


@pytest.mark.asyncio
async def test_main_logging_setup():
    """Test that main() sets up logging correctly.

    Verifies setup_logging called with INFO level.
    """
    with patch('main.setup_logging') as mock_setup_logging, \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url'), \
         patch('main.init_db'), \
         patch('main.read_secret'), \
         patch('main.create_bot'), \
         patch('main.create_dispatcher') as mock_create_dispatcher, \
         patch('main.dispose_db'):

        mock_get_logger.return_value = MagicMock()
        mock_dispatcher = MagicMock()
        mock_dispatcher.start_polling = AsyncMock()
        mock_create_dispatcher.return_value = mock_dispatcher

        await main()

        # Verify logging setup
        mock_setup_logging.assert_called_once_with(level="INFO")


@pytest.mark.asyncio
async def test_main_logging_sequence():
    """Test that main() logs all startup steps.

    Verifies logging of: bot_starting, database_initialized,
    secrets_loaded, starting_polling, bot_stopped.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger') as mock_get_logger, \
         patch('main.get_database_url'), \
         patch('main.init_db'), \
         patch('main.read_secret'), \
         patch('main.create_bot'), \
         patch('main.create_dispatcher') as mock_create_dispatcher, \
         patch('main.dispose_db'):

        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger
        mock_dispatcher = MagicMock()
        mock_dispatcher.start_polling = AsyncMock()
        mock_create_dispatcher.return_value = mock_dispatcher

        await main()

        # Collect logged events
        info_calls = [c[0][0] for c in mock_logger.info.call_args_list]

        # Verify sequence
        assert "bot_starting" in info_calls
        assert "database_initialized" in info_calls
        assert "secrets_loaded" in info_calls
        assert "starting_polling" in info_calls
        assert "bot_stopped" in info_calls

        # Verify order
        starting_idx = info_calls.index("bot_starting")
        db_idx = info_calls.index("database_initialized")
        secrets_idx = info_calls.index("secrets_loaded")
        polling_idx = info_calls.index("starting_polling")
        stopped_idx = info_calls.index("bot_stopped")

        assert starting_idx < db_idx < secrets_idx < polling_idx < stopped_idx


@pytest.mark.asyncio
async def test_main_dispatcher_start_polling():
    """Test that main() starts dispatcher polling.

    Verifies start_polling called with bot instance.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger'), \
         patch('main.get_database_url'), \
         patch('main.init_db'), \
         patch('main.read_secret'), \
         patch('main.create_bot') as mock_create_bot, \
         patch('main.create_dispatcher') as mock_create_dispatcher, \
         patch('main.dispose_db'):

        mock_bot = MagicMock()
        mock_create_bot.return_value = mock_bot
        mock_dispatcher = MagicMock()
        mock_dispatcher.start_polling = AsyncMock()
        mock_create_dispatcher.return_value = mock_dispatcher

        await main()

        # Verify polling started with bot
        mock_dispatcher.start_polling.assert_called_once_with(mock_bot)


@pytest.mark.asyncio
async def test_main_database_echo_disabled():
    """Test that main() initializes database with echo=False.

    Verifies SQL logging is disabled in production.
    """
    with patch('main.setup_logging'), \
         patch('main.get_logger'), \
         patch('main.get_database_url'), \
         patch('main.init_db') as mock_init_db, \
         patch('main.read_secret'), \
         patch('main.create_bot'), \
         patch('main.create_dispatcher') as mock_create_dispatcher, \
         patch('main.dispose_db'):

        mock_dispatcher = MagicMock()
        mock_dispatcher.start_polling = AsyncMock()
        mock_create_dispatcher.return_value = mock_dispatcher

        await main()

        # Verify echo=False
        call_kwargs = mock_init_db.call_args[1]
        assert call_kwargs['echo'] is False


def test_read_secret_encoding_utf8():
    """Test that read_secret uses UTF-8 encoding.

    Verifies correct encoding for international characters.
    """
    with patch('main.Path') as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.read_text.return_value = "test"

        read_secret("test")

        # Verify encoding
        mock_instance.read_text.assert_called_once_with(encoding='utf-8')


def test_read_secret_path_format():
    """Test read_secret constructs correct path.

    Verifies /run/secrets/ directory is used.
    """
    with patch('main.Path') as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.read_text.return_value = "test"

        read_secret("my_secret")

        # Verify path
        mock_path.assert_called_once_with("/run/secrets/my_secret")
