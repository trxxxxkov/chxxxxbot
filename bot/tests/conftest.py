"""Pytest fixtures for repository tests.

This module provides shared fixtures for all repository tests, including
in-memory SQLite database setup and sample data fixtures.

NO __init__.py - use direct import:
    from tests.conftest import test_session, sample_user
"""

import asyncio
from datetime import datetime
from datetime import timezone
from typing import AsyncGenerator

from db.models.base import Base
from db.models.chat import Chat
from db.models.message import Message
from db.models.message import MessageRole
from db.models.thread import Thread
from db.models.user import User
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture(scope='session')
def event_loop():
    """Create event loop for async tests.

    Yields:
        asyncio.AbstractEventLoop: Event loop for the test session.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_db_engine():
    """Create in-memory SQLite async engine for testing.

    Uses in-memory SQLite for fast tests without requiring PostgreSQL.
    Creates all tables on setup and disposes engine on teardown.

    Yields:
        AsyncEngine: SQLAlchemy async engine connected to in-memory SQLite.
    """
    # Create in-memory SQLite database
    # Note: implicit_returning=False to avoid RETURNING issues with SQLite BigInteger
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        echo=False,
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
        execution_options={"compiled_cache": None},
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Dispose engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_db_engine,) -> AsyncGenerator[AsyncSession, None]:
    """Create async session with automatic rollback for test isolation.

    Each test gets its own transaction that is rolled back after the test,
    ensuring test isolation.

    Args:
        test_db_engine: Async engine fixture.

    Yields:
        AsyncSession: SQLAlchemy async session with rollback on teardown.
    """
    # Create session factory
    session_factory = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        # Begin nested transaction for rollback
        async with session.begin():
            yield session
            # Rollback happens automatically when context exits


@pytest_asyncio.fixture
async def sample_user(test_session: AsyncSession) -> User:
    """Create sample user for testing.

    Args:
        test_session: Async session fixture.

    Returns:
        User: Sample user with test data.
    """
    user = User(
        id=123456789,
        first_name='Test',
        last_name='User',
        username='test_user',
        language_code='en',
        is_premium=False,
        model_id='claude:sonnet',  # Phase 1.4.2: per-user model selection
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    test_session.add(user)
    await test_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_chat(test_session: AsyncSession) -> Chat:
    """Create sample chat for testing.

    Args:
        test_session: Async session fixture.

    Returns:
        Chat: Sample private chat with test data.
    """
    chat = Chat(
        id=987654321,
        type='private',
        title=None,
        username='test_user',
        first_name='Test',
        last_name='User',
        is_forum=False,
    )
    test_session.add(chat)
    await test_session.flush()
    return chat


@pytest_asyncio.fixture
async def sample_thread(
    test_session: AsyncSession,
    sample_user: User,
    sample_chat: Chat,
) -> Thread:
    """Create sample thread for testing.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.

    Returns:
        Thread: Sample thread linking user and chat.
    """
    thread = Thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,  # Main chat (not forum topic)
    )
    test_session.add(thread)
    await test_session.flush()
    return thread


@pytest_asyncio.fixture
async def sample_message(
    test_session: AsyncSession,
    sample_thread: Thread,
    sample_user: User,
    sample_chat: Chat,
) -> Message:
    """Create sample message for testing.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.

    Returns:
        Message: Sample text message with test data.
    """
    message = Message(
        chat_id=sample_chat.id,
        message_id=1,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567890,
        role=MessageRole.USER,
        text_content='Hello, bot!',
        attachments=[],
        has_photos=False,
        has_documents=False,
        has_voice=False,
        has_video=False,
        attachment_count=0,
        created_at=1234567890,
    )
    test_session.add(message)
    await test_session.flush()
    return message
