"""Async PostgreSQL engine and session management.

This module provides async database engine, session factory, and session
management utilities for use throughout the bot application.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Global engine and session factory (initialized in init_db)
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def init_db(database_url: str, echo: bool = False) -> None:
    """Initialize database engine and session factory.

    Should be called once at application startup from main.py.
    Connection pool is configured for long-running bot workloads:
    - QueuePool with 5 base connections
    - Up to 10 overflow connections during load spikes
    - Pre-ping to auto-reconnect on stale connections
    - Connections recycled every hour

    Args:
        database_url: PostgreSQL connection URL in format:
            postgresql+asyncpg://user:password@host:port/database
        echo: If True, log all SQL statements (useful for debugging).
            Defaults to False.
    """
    global _engine, _session_factory  # pylint: disable=global-statement

    # Import all models to register them with SQLAlchemy mapper
    # This must happen before any queries that use relationships
    # pylint: disable=import-outside-toplevel,unused-import
    from db.models.balance_operation import BalanceOperation  # noqa: F401
    from db.models.chat import Chat  # noqa: F401
    from db.models.message import Message  # noqa: F401
    from db.models.payment import Payment  # noqa: F401
    from db.models.thread import Thread  # noqa: F401
    from db.models.tool_call import ToolCall  # noqa: F401
    from db.models.user import User  # noqa: F401
    from db.models.user_file import UserFile  # noqa: F401

    # pylint: enable=import-outside-toplevel,unused-import
    # Connection pool configuration optimized for Telegram bot
    # pool_size=5: Max 5 base connections
    # max_overflow=10: Allow up to 10 additional connections during spikes
    # pool_pre_ping=True: Test connections before using (auto-reconnect)
    # pool_recycle=3600: Recycle connections after 1 hour
    # Note: create_async_engine uses AsyncAdaptedQueuePool by default
    _engine = create_async_engine(
        database_url,
        echo=echo,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_timeout=30,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,  # Don't expire objects after commit
        autoflush=False,  # Manual flush control for better performance
        autocommit=False,
    )

    # Log without exposing password
    safe_url = database_url.split('@')[-1] if '@' in database_url else 'local'
    logger.info("database_initialized", url=safe_url)


async def dispose_db() -> None:
    """Dispose database engine and close all connections.

    Should be called on application shutdown to cleanly close all
    database connections and release resources.
    """
    global _engine  # pylint: disable=global-statement,global-variable-not-assigned
    if _engine:
        await _engine.dispose()
        logger.info("database_disposed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session with automatic cleanup.

    Creates a new session, yields it for use, and ensures proper cleanup
    with automatic commit on success or rollback on error.

    Usage:
        async with get_session() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()

    Yields:
        AsyncSession: Database session with automatic commit/rollback.

    Raises:
        RuntimeError: If database not initialized via init_db().
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get session factory for dependency injection.

    Used by middleware to inject sessions into handlers. The middleware
    will manage session lifecycle (commit/rollback/close).

    Returns:
        async_sessionmaker: Session factory for creating new sessions.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


def get_pool_stats() -> dict:
    """Get database connection pool statistics.

    Returns dict with:
        - active: Number of connections currently in use
        - idle: Number of connections idle in pool
        - overflow: Number of overflow connections created
        - pool_size: Configured pool size
        - max_overflow: Max allowed overflow

    Returns:
        Dict with pool statistics, or empty dict if engine not initialized.
    """
    if _engine is None:
        return {}

    pool = _engine.pool
    return {
        "active": pool.checkedout(),
        "idle": pool.checkedin(),
        "overflow": pool.overflow(),
        "pool_size": pool.size(),
        "max_overflow": pool._max_overflow,
    }
