"""Tests for database engine and session management.

This module contains comprehensive tests for db/engine.py, testing
the async database engine, connection pool configuration, and session
lifecycle management.

NO __init__.py - use direct import:
    pytest tests/db/test_engine.py
"""

from unittest.mock import AsyncMock
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch

from db import engine
import pytest


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset global engine and session factory before each test.

    This ensures test isolation by clearing module-level state.
    """
    engine._engine = None
    engine._session_factory = None
    yield
    engine._engine = None
    engine._session_factory = None


@pytest.mark.asyncio
async def test_init_db_creates_engine_and_factory():
    """Test that init_db creates both engine and session factory.

    Verifies that calling init_db() initializes the global _engine
    and _session_factory variables.
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        mock_factory = MagicMock()
        mock_sessionmaker.return_value = mock_factory

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        assert engine._engine is mock_engine
        assert engine._session_factory is mock_factory


@pytest.mark.asyncio
async def test_init_db_with_valid_url():
    """Test init_db with valid PostgreSQL URL.

    Verifies that create_async_engine is called with the provided URL.
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker'):

        test_url = 'postgresql+asyncpg://user:password@localhost:5432/testdb'
        engine.init_db(test_url)

        mock_create_engine.assert_called_once()
        call_args = mock_create_engine.call_args
        assert call_args[0][0] == test_url


@pytest.mark.asyncio
async def test_init_db_pool_config():
    """Test that init_db configures connection pool correctly.

    Verifies connection pool settings:
    - pool_size=5 (base connections)
    - max_overflow=10 (additional connections)
    - pool_pre_ping=True (test before use)
    - pool_recycle=3600 (recycle every hour)
    - pool_timeout=30 (wait up to 30 seconds)
    Note: create_async_engine uses AsyncAdaptedQueuePool by default
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker'):

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        call_kwargs = mock_create_engine.call_args[1]
        # poolclass not specified - uses AsyncAdaptedQueuePool by default
        assert 'poolclass' not in call_kwargs
        assert call_kwargs['pool_size'] == 5
        assert call_kwargs['max_overflow'] == 10
        assert call_kwargs['pool_pre_ping'] is True
        assert call_kwargs['pool_recycle'] == 3600
        assert call_kwargs['pool_timeout'] == 30


@pytest.mark.asyncio
async def test_init_db_session_maker_config():
    """Test that init_db configures async_sessionmaker correctly.

    Verifies session factory settings:
    - expire_on_commit=False
    - autoflush=False
    - autocommit=False
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        from sqlalchemy.ext.asyncio import AsyncSession

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        mock_sessionmaker.assert_called_once_with(
            bind=mock_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )


@pytest.mark.asyncio
async def test_init_db_logs_safely():
    """Test that init_db logs without exposing password.

    Verifies that database URL password is not logged.
    """
    with patch('db.engine.create_async_engine'), \
         patch('db.engine.async_sessionmaker'), \
         patch('db.engine.logger') as mock_logger:

        url_with_password = 'postgresql+asyncpg://user:secret123@localhost:5432/db'
        engine.init_db(url_with_password)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args

        # Verify "database_initialized" event logged
        assert call_args[0][0] == 'database_initialized'

        # Verify password not in logged URL
        logged_url = call_args[1]['url']
        assert 'secret123' not in logged_url
        assert 'localhost:5432/db' in logged_url


@pytest.mark.asyncio
async def test_init_db_with_echo_true():
    """Test init_db with echo=True for SQL logging.

    Verifies that echo parameter is passed to create_async_engine.
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker'):

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db', echo=True)

        call_kwargs = mock_create_engine.call_args[1]
        assert call_kwargs['echo'] is True


@pytest.mark.asyncio
async def test_multiple_init_db_calls():
    """Test that multiple init_db calls replace previous engine.

    Verifies that calling init_db() multiple times overwrites
    global variables (useful for testing or reconnection).
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        mock_engine1 = MagicMock(name='engine1')
        mock_engine2 = MagicMock(name='engine2')
        mock_factory1 = MagicMock(name='factory1')
        mock_factory2 = MagicMock(name='factory2')

        mock_create_engine.side_effect = [mock_engine1, mock_engine2]
        mock_sessionmaker.side_effect = [mock_factory1, mock_factory2]

        # First init
        engine.init_db('postgresql+asyncpg://user:pass@host1/db')
        assert engine._engine is mock_engine1
        assert engine._session_factory is mock_factory1

        # Second init (overwrites)
        engine.init_db('postgresql+asyncpg://user:pass@host2/db')
        assert engine._engine is mock_engine2
        assert engine._session_factory is mock_factory2


@pytest.mark.asyncio
async def test_dispose_db_closes_connections():
    """Test that dispose_db calls engine.dispose().

    Verifies that database connections are properly closed.
    """
    with patch('db.engine.create_async_engine') as mock_create_engine, \
         patch('db.engine.async_sessionmaker'), \
         patch('db.engine.logger') as mock_logger:

        mock_engine = AsyncMock()
        mock_create_engine.return_value = mock_engine

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')
        await engine.dispose_db()

        mock_engine.dispose.assert_called_once()
        mock_logger.info.assert_called_with('database_disposed')


@pytest.mark.asyncio
async def test_dispose_db_when_engine_none():
    """Test dispose_db when engine is None (not initialized).

    Verifies that dispose_db() safely handles uninitialized state.
    """
    with patch('db.engine.logger') as mock_logger:
        engine._engine = None

        # Should not raise exception
        await engine.dispose_db()

        # Should not log anything
        calls = [
            c for c in mock_logger.info.call_args_list
            if c[0][0] == 'database_disposed'
        ]
        assert len(calls) == 0


@pytest.mark.asyncio
async def test_get_session_yields_async_session():
    """Test that get_session yields AsyncSession instance.

    Verifies session creation, usage, commit, and cleanup.
    """
    with patch('db.engine.create_async_engine'), \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)
        mock_sessionmaker.return_value = mock_factory

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        async with engine.get_session() as session:
            assert session is mock_session

        # Verify lifecycle
        mock_session.commit.assert_called_once()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_session_raises_if_not_initialized():
    """Test that get_session raises RuntimeError if not initialized.

    Verifies proper error handling when init_db() not called.
    """
    engine._session_factory = None

    with pytest.raises(RuntimeError, match="Database not initialized"):
        async with engine.get_session():
            pass


@pytest.mark.asyncio
async def test_get_session_rollback_on_error():
    """Test that get_session rolls back on exception.

    Verifies that exceptions trigger rollback and are propagated.
    """
    with patch('db.engine.create_async_engine'), \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)
        mock_sessionmaker.return_value = mock_factory

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        with pytest.raises(ValueError, match="Test error"):
            async with engine.get_session():
                raise ValueError("Test error")

        # Verify rollback called, not commit
        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_session_cleanup_in_finally():
    """Test that get_session always closes session in finally block.

    Verifies session cleanup happens even on exception.
    """
    with patch('db.engine.create_async_engine'), \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        mock_session = AsyncMock()
        mock_factory = MagicMock(return_value=mock_session)
        mock_sessionmaker.return_value = mock_factory

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        try:
            async with engine.get_session():
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        # Session must be closed even after exception
        mock_session.close.assert_called_once()


def test_get_session_factory_returns_factory():
    """Test that get_session_factory returns session factory.

    Verifies factory retrieval for dependency injection.
    """
    with patch('db.engine.create_async_engine'), \
         patch('db.engine.async_sessionmaker') as mock_sessionmaker:

        mock_factory = MagicMock()
        mock_sessionmaker.return_value = mock_factory

        engine.init_db('postgresql+asyncpg://user:pass@localhost/db')

        factory = engine.get_session_factory()

        assert factory is mock_factory


def test_get_session_factory_raises_if_not_initialized():
    """Test get_session_factory raises RuntimeError if not initialized.

    Verifies proper error handling for dependency injection.
    """
    engine._session_factory = None

    with pytest.raises(RuntimeError, match="Database not initialized"):
        engine.get_session_factory()
