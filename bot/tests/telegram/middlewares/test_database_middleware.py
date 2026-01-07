"""Tests for database middleware.

This module contains comprehensive tests for
telegram/middlewares/database_middleware.py, testing session lifecycle,
transaction management (commit/rollback), and dependency injection.

NO __init__.py - use direct import:
    pytest tests/telegram/middlewares/test_database_middleware.py
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.middlewares.database_middleware import DatabaseMiddleware


@pytest.fixture
def middleware():
    """Create DatabaseMiddleware instance.

    Returns:
        DatabaseMiddleware instance for testing.
    """
    return DatabaseMiddleware()


@pytest.fixture
def mock_update():
    """Create mock Telegram Update object.

    Returns:
        Mock Update with update_id.
    """
    update = MagicMock()
    update.update_id = 123456
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


@pytest.fixture
def mock_session():
    """Create mock AsyncSession.

    Returns:
        Mock session with commit, rollback, close methods.
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_database_middleware_success_flow(middleware, mock_update,
                                                mock_handler, mock_session):
    """Test middleware with successful handler execution.

    Verifies session creation, injection, commit, and cleanup.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()

    # Mock context manager behavior
    async def mock_context_manager():
        yield mock_session

    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {}
        result = await middleware(mock_handler, mock_update, data)

        # Verify session injected into data
        assert 'session' in data
        assert data['session'] is mock_session

        # Verify handler called
        mock_handler.assert_called_once_with(mock_update, data)

        # Verify commit called
        mock_session.commit.assert_called_once()

        # Verify result returned
        assert result == "handler_result"


@pytest.mark.asyncio
async def test_database_middleware_session_injection(middleware, mock_update,
                                                     mock_session):
    """Test that session is injected into handler data.

    Verifies dependency injection pattern.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock()

    captured_data = {}

    async def capturing_handler(event, data):
        # Capture data to verify session injection
        captured_data.update(data)
        return "ok"

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {"other_key": "other_value"}
        await middleware(capturing_handler, mock_update, data)

        # Verify session in captured data
        assert 'session' in captured_data
        assert captured_data['session'] is mock_session

        # Verify other data preserved
        assert captured_data['other_key'] == "other_value"


@pytest.mark.asyncio
async def test_database_middleware_commit_on_success(middleware, mock_update,
                                                     mock_handler,
                                                     mock_session):
    """Test that session is committed on successful handler execution.

    Verifies auto-commit behavior.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock()

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {}
        await middleware(mock_handler, mock_update, data)

        # Verify commit called
        mock_session.commit.assert_called_once()

        # Verify rollback NOT called
        mock_session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_database_middleware_rollback_on_error(middleware, mock_update,
                                                     mock_session):
    """Test that session is rolled back on handler exception.

    Verifies auto-rollback behavior and exception propagation.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    # __aexit__ should return None (or False) to propagate exceptions
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    failing_handler = AsyncMock(side_effect=ValueError("Handler error"))

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {}

        # Exception should be re-raised
        with pytest.raises(ValueError, match="Handler error"):
            await middleware(failing_handler, mock_update, data)

    # Verify rollback called (check after context exits)
    mock_session.rollback.assert_called_once()

    # Verify commit NOT called
    mock_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_database_middleware_session_cleanup(middleware, mock_update,
                                                   mock_handler, mock_session):
    """Test that session is cleaned up in async context manager.

    Verifies session lifecycle management.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()

    # Track __aexit__ call
    aexit_called = []

    async def mock_aexit(*args):
        aexit_called.append(True)
        return None

    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = mock_aexit

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {}
        await middleware(mock_handler, mock_update, data)

        # Verify __aexit__ called (cleanup)
        assert len(aexit_called) == 1


@pytest.mark.asyncio
async def test_database_middleware_multiple_updates(middleware, mock_handler):
    """Test middleware handles multiple sequential updates.

    Verifies session isolation between updates.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_handler: Mock handler function.
    """
    update1 = MagicMock()
    update1.update_id = 111
    update2 = MagicMock()
    update2.update_id = 222

    session1 = AsyncMock()
    session2 = AsyncMock()

    call_count = [0]

    def create_session_factory():
        factory = MagicMock()
        call_count[0] += 1
        current_session = session1 if call_count[0] == 1 else session2
        factory.return_value.__aenter__ = AsyncMock(
            return_value=current_session)
        factory.return_value.__aexit__ = AsyncMock()
        return factory

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               side_effect=create_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        # Process update 1
        data1 = {}
        await middleware(mock_handler, update1, data1)
        assert data1['session'] is session1

        # Process update 2
        data2 = {}
        await middleware(mock_handler, update2, data2)
        assert data2['session'] is session2

        # Sessions are different (isolated)
        assert data1['session'] is not data2['session']


@pytest.mark.asyncio
async def test_database_middleware_database_error(middleware, mock_update,
                                                  mock_session):
    """Test middleware handles database errors.

    Verifies rollback on database exceptions.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_session: Mock AsyncSession.
    """
    from sqlalchemy.exc import IntegrityError

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    # __aexit__ should return None to propagate exceptions
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    # Handler raises database error
    handler = AsyncMock(
        side_effect=IntegrityError("statement", "params", "orig"))

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {}

        with pytest.raises(IntegrityError):
            await middleware(handler, mock_update, data)

    # Verify rollback called (check after context exits)
    mock_session.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_database_middleware_logging(middleware, mock_update,
                                           mock_handler, mock_session):
    """Test middleware logs commit and rollback.

    Verifies logging of database operations.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_handler: Mock handler function.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock()

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger') as mock_logger:

        data = {}
        await middleware(mock_handler, mock_update, data)

        # Verify commit logged
        mock_logger.debug.assert_called_once_with("database_session_committed",
                                                  update_id=123456)


@pytest.mark.asyncio
async def test_database_middleware_rollback_logging(middleware, mock_update,
                                                    mock_session):
    """Test middleware logs rollback on error.

    Verifies error logging with exception details.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    # __aexit__ should return None to propagate exceptions
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    handler = AsyncMock(side_effect=RuntimeError("Test error"))

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger') as mock_logger:

        data = {}

        with pytest.raises(RuntimeError):
            await middleware(handler, mock_update, data)

    # Verify rollback logged (check after context exits)
    mock_logger.error.assert_called_once()
    error_call = mock_logger.error.call_args

    assert error_call[0][0] == "database_session_rollback"
    assert error_call[1]['error'] == "Test error"
    assert error_call[1]['error_type'] == "RuntimeError"
    assert error_call[1]['update_id'] == 123456


@pytest.mark.asyncio
async def test_database_middleware_handler_chain(middleware, mock_update,
                                                 mock_session):
    """Test middleware in handler chain.

    Verifies handler receives event and data correctly.

    Args:
        middleware: DatabaseMiddleware fixture.
        mock_update: Mock Update object.
        mock_session: Mock AsyncSession.
    """
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock()

    handler = AsyncMock(return_value="chain_result")

    with patch('telegram.middlewares.database_middleware.get_session_factory',
               return_value=mock_session_factory), \
         patch('telegram.middlewares.database_middleware.logger'):

        data = {"original_key": "original_value"}
        result = await middleware(handler, mock_update, data)

        # Verify handler called with event and data
        handler.assert_called_once_with(mock_update, data)

        # Verify original data preserved
        assert data['original_key'] == "original_value"

        # Verify session added
        assert 'session' in data

        # Verify result returned
        assert result == "chain_result"
