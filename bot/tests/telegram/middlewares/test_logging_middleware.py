"""Tests for logging middleware.

This module contains comprehensive tests for
telegram/middlewares/logging_middleware.py, testing context extraction,
execution time measurement, and error logging.

NO __init__.py - use direct import:
    pytest tests/telegram/middlewares/test_logging_middleware.py
"""

from unittest.mock import ANY
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.middlewares.logging_middleware import LoggingMiddleware


@pytest.fixture
def middleware():
    """Create LoggingMiddleware instance.

    Returns:
        LoggingMiddleware instance for testing.
    """
    return LoggingMiddleware()


@pytest.fixture
def mock_update():
    """Create mock Telegram Update object.

    Returns:
        Mock Update with message and user.
    """
    update = MagicMock()
    update.update_id = 123456
    update.message = MagicMock()
    update.message.message_id = 789
    update.message.chat = MagicMock()
    update.message.chat.id = 555555
    update.message.from_user = MagicMock()
    update.message.from_user.id = 987654321
    update.message.from_user.username = "testuser"
    update.event_type = "message"
    return update


@pytest.fixture
def mock_handler():
    """Create mock handler function.

    Returns:
        Async mock that simulates handler.
    """
    handler = AsyncMock()
    handler.return_value = "handler_result"
    return handler


@pytest.mark.asyncio
async def test_logging_middleware_message_update(middleware, mock_update,
                                                 mock_handler):
    """Test middleware with normal message update.

    Verifies context extraction and logging.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
    """
    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        result = await middleware(mock_handler, mock_update, data)

        # Verify context binding (includes request_id, chat_id, username)
        mock_logger.bind.assert_called_once_with(
            request_id=ANY,  # UUID, can't predict
            update_id=123456,
            user_id=987654321,
            username="testuser",
            message_id=789,
            chat_id=555555,
        )

        # Verify incoming_update logged
        calls = [call[0][0] for call in mock_bound_logger.info.call_args_list]
        assert "incoming_update" in calls

        # Verify update_processed logged
        assert "update_processed" in calls

        # Verify handler called
        mock_handler.assert_called_once_with(mock_update, data)

        # Verify result returned
        assert result == "handler_result"


@pytest.mark.asyncio
async def test_logging_middleware_callback_update(middleware, mock_handler):
    """Test middleware with callback query update.

    Verifies callback_query context extraction.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_handler: Mock handler function.
    """
    update = MagicMock()
    update.update_id = 111
    update.message = None
    update.callback_query = MagicMock()
    update.callback_query.from_user = MagicMock()
    update.callback_query.from_user.id = 222
    update.callback_query.from_user.username = "callbackuser"
    update.event_type = "callback_query"

    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        await middleware(mock_handler, update, data)

        # Verify context includes callback user_id, username (and request_id, chat_id)
        mock_logger.bind.assert_called_once_with(
            request_id=ANY,
            update_id=111,
            user_id=222,
            username="callbackuser",
            message_id=None,
            chat_id=None,
        )


@pytest.mark.asyncio
async def test_logging_middleware_no_user(middleware, mock_handler):
    """Test middleware when from_user is None.

    Verifies graceful handling of anonymous updates.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_handler: Mock handler function.
    """
    update = MagicMock()
    update.update_id = 333
    update.message = MagicMock()
    update.message.message_id = 444
    update.message.chat = MagicMock()
    update.message.chat.id = 666
    update.message.from_user = None
    update.event_type = "message"

    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        await middleware(mock_handler, update, data)

        # Verify user_id and username are None (but chat_id and request_id present)
        mock_logger.bind.assert_called_once_with(
            request_id=ANY,
            update_id=333,
            user_id=None,
            username=None,
            message_id=444,
            chat_id=666,
        )


@pytest.mark.asyncio
async def test_logging_middleware_execution_time(middleware, mock_update,
                                                 mock_handler):
    """Test that middleware measures execution time.

    Verifies execution_time_ms is logged.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
    """
    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        await middleware(mock_handler, mock_update, data)

        # Find update_processed call
        calls = mock_bound_logger.info.call_args_list
        processed_call = [c for c in calls if c[0][0] == "update_processed"][0]

        # Verify execution_time_ms present and is float
        exec_time = processed_call[1]['execution_time_ms']
        assert isinstance(exec_time, (int, float))
        assert exec_time >= 0


@pytest.mark.asyncio
async def test_logging_middleware_exception_logging(middleware, mock_update):
    """Test middleware logs exceptions with traceback.

    Verifies error logging and exception re-raising.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_update: Mock Update object.
    """
    handler = AsyncMock(side_effect=ValueError("Test error"))

    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.error = MagicMock()
        mock_bound_logger.info = MagicMock()

        data = {}

        # Exception should be re-raised
        with pytest.raises(ValueError, match="Test error"):
            await middleware(handler, mock_update, data)

        # Verify error logged
        mock_bound_logger.error.assert_called_once()
        error_call = mock_bound_logger.error.call_args

        assert error_call[0][0] == "update_error"
        assert error_call[1]['error'] == "Test error"
        assert error_call[1]['error_type'] == "ValueError"
        assert 'execution_time_ms' in error_call[1]
        assert error_call[1]['exc_info'] is True


@pytest.mark.asyncio
async def test_logging_middleware_context_binding(middleware, mock_update,
                                                  mock_handler):
    """Test that context is properly bound to logger.

    Verifies logger.bind() creates isolated context.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
    """
    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        await middleware(mock_handler, mock_update, data)

        # Verify bind called with correct context
        bind_call = mock_logger.bind.call_args
        assert bind_call[1]['update_id'] == 123456
        assert bind_call[1]['user_id'] == 987654321
        assert bind_call[1]['message_id'] == 789
        assert bind_call[1]['chat_id'] == 555555
        assert 'request_id' in bind_call[1]

        # Verify bound logger used for logging
        assert mock_bound_logger.info.call_count == 2


@pytest.mark.asyncio
async def test_logging_middleware_event_type(middleware, mock_handler):
    """Test that event_type is logged.

    Verifies update_type parameter in incoming_update log.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_handler: Mock handler function.
    """
    update = MagicMock()
    update.update_id = 555
    update.message = None
    update.event_type = "edited_message"

    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        await middleware(mock_handler, update, data)

        # Find incoming_update call
        calls = mock_bound_logger.info.call_args_list
        incoming_call = [c for c in calls if c[0][0] == "incoming_update"][0]

        # Verify update_type
        assert incoming_call[1]['update_type'] == "edited_message"


@pytest.mark.asyncio
async def test_logging_middleware_handler_chain(middleware, mock_update):
    """Test middleware in handler chain.

    Verifies that handler is called with correct arguments.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_update: Mock Update object.
    """
    handler = AsyncMock(return_value="chain_result")

    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {"existing_key": "existing_value"}
        result = await middleware(handler, mock_update, data)

        # Verify handler called with event and data
        handler.assert_called_once_with(mock_update, data)

        # Verify data preserved
        assert data['existing_key'] == "existing_value"

        # Verify result returned
        assert result == "chain_result"


@pytest.mark.asyncio
async def test_logging_middleware_unknown_event(middleware, mock_handler):
    """Test middleware with unknown event type.

    Verifies graceful handling when event_type attribute missing.

    Args:
        middleware: LoggingMiddleware fixture.
        mock_handler: Mock handler function.
    """
    update = MagicMock(spec=['update_id'])  # No event_type attribute
    update.update_id = 666
    update.message = None
    update.callback_query = None

    with patch('telegram.middlewares.logging_middleware.logger') as mock_logger, \
         patch('telegram.middlewares.logging_middleware.structlog') as mock_structlog:
        mock_bound_logger = MagicMock()
        mock_logger.bind.return_value = mock_bound_logger
        mock_bound_logger.info = MagicMock()

        data = {}
        await middleware(mock_handler, update, data)

        # Find incoming_update call
        calls = mock_bound_logger.info.call_args_list
        incoming_call = [c for c in calls if c[0][0] == "incoming_update"][0]

        # Should default to "unknown"
        assert incoming_call[1]['update_type'] == "unknown"
