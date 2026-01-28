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

from db.models.balance_operation import BalanceOperation
from db.models.base import Base
from db.models.chat import Chat
from db.models.message import Message
from db.models.message import MessageRole
from db.models.payment import Payment
from db.models.thread import Thread
from db.models.user import User
from db.models.user_file import UserFile
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
async def integration_session(
    test_db_engine,) -> AsyncGenerator[AsyncSession, None]:
    """Create async session for integration tests that need to commit.

    Unlike test_session, this fixture allows commits within tests.
    Used for integration tests that call service methods with commits.

    Args:
        test_db_engine: Async engine fixture.

    Yields:
        AsyncSession: SQLAlchemy async session.
    """
    # Create session factory
    session_factory = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        # Rollback any uncommitted changes
        await session.rollback()


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
async def integration_sample_user(integration_session: AsyncSession) -> User:
    """Create sample user for integration tests.

    Args:
        integration_session: Integration session fixture.

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
        model_id='claude:sonnet',
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    integration_session.add(user)
    await integration_session.commit()
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


"""Pytest fixtures for payment system tests using PostgreSQL.

Phase 2.1: Payment system tests require PostgreSQL enum types.
These fixtures connect to the real PostgreSQL database from Docker Compose.
"""

import asyncio
from typing import AsyncGenerator

from config import get_database_url
from db.models.base import Base
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine


@pytest_asyncio.fixture
async def pg_engine():
    """Create async engine connected to PostgreSQL from Docker Compose.

    This fixture connects to the real PostgreSQL database used by the bot.
    Migrations must be applied before running tests.

    Yields:
        AsyncEngine: SQLAlchemy async engine connected to PostgreSQL.
    """
    # Get database URL from config (same as production)
    from config import get_database_url
    database_url = get_database_url()

    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )

    yield engine

    # Dispose engine
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create async session with automatic rollback for test isolation.

    Each test gets its own transaction that is rolled back after the test,
    ensuring test isolation without affecting other tests or production data.

    Args:
        pg_engine: PostgreSQL async engine fixture.

    Yields:
        AsyncSession: SQLAlchemy async session with rollback on teardown.
    """
    # Create session factory
    session_factory = async_sessionmaker(
        pg_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Connect and start transaction
    async with pg_engine.connect() as connection:
        # Begin transaction
        async with connection.begin() as transaction:
            # Create session bound to this connection
            async with session_factory(bind=connection) as session:
                # Nested transaction for savepoint
                await session.begin_nested()

                try:
                    yield session
                finally:
                    # Rollback everything
                    await transaction.rollback()


@pytest_asyncio.fixture
async def pg_sample_user(pg_session: AsyncSession):
    """Create sample user for payment tests using PostgreSQL.

    Each test gets a unique user ID to avoid conflicts.

    Args:
        pg_session: PostgreSQL async session fixture.

    Returns:
        User: Sample user with test data.
    """
    from datetime import datetime
    from datetime import timezone
    import random

    from db.models.user import User

    # Generate unique user ID for each test (random in range 100000000-999999999)
    unique_id = random.randint(100000000, 999999999)

    user = User(
        id=unique_id,
        first_name='Test',
        last_name='User',
        username=f'test_user_{unique_id}',
        language_code='en',
        is_premium=False,
        model_id='claude:sonnet',
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    pg_session.add(user)
    await pg_session.flush()
    return user


@pytest_asyncio.fixture
async def pg_admin_user(pg_session: AsyncSession):
    """Create admin user for payment tests using PostgreSQL.

    Args:
        pg_session: PostgreSQL async session fixture.

    Returns:
        User: Admin user with test data.
    """
    from datetime import datetime
    from datetime import timezone
    import random

    from db.models.user import User

    # Generate unique admin ID
    unique_id = random.randint(900000000, 999999999)

    user = User(
        id=unique_id,
        username=f"admin_{unique_id}",
        first_name="Admin",
        last_name="User",
        is_bot=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    pg_session.add(user)
    await pg_session.flush()
    return user


# ============================================================================
# Phase 5.5: Telegram Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_telegram_user():
    """Create mock Telegram user object.

    Returns:
        MagicMock: Mock aiogram User with common attributes.
    """
    from unittest.mock import MagicMock

    user = MagicMock()
    user.id = 123456789
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "test_user"
    user.language_code = "en"
    user.is_premium = False
    user.is_bot = False
    return user


@pytest.fixture
def mock_telegram_chat():
    """Create mock Telegram chat object.

    Returns:
        MagicMock: Mock aiogram Chat with common attributes.
    """
    from unittest.mock import MagicMock

    chat = MagicMock()
    chat.id = 987654321
    chat.type = "private"
    chat.title = None
    chat.username = "test_user"
    chat.first_name = "Test"
    chat.last_name = "User"
    return chat


@pytest.fixture
def mock_telegram_message(mock_telegram_user, mock_telegram_chat):
    """Create mock Telegram message object.

    Args:
        mock_telegram_user: Mock user fixture.
        mock_telegram_chat: Mock chat fixture.

    Returns:
        MagicMock: Mock aiogram Message with common attributes and methods.
    """
    from unittest.mock import AsyncMock
    from unittest.mock import MagicMock

    message = MagicMock()
    message.message_id = 1
    message.date = datetime.now(timezone.utc)
    message.chat = mock_telegram_chat
    message.from_user = mock_telegram_user
    message.text = "Hello, bot!"
    message.caption = None
    message.photo = None
    message.document = None
    message.voice = None
    message.video = None
    message.audio = None
    message.message_thread_id = None

    # Mock bot
    message.bot = MagicMock()
    message.bot.get_file = AsyncMock()
    message.bot.download_file = AsyncMock()
    message.bot.send_message = AsyncMock()
    message.bot.send_photo = AsyncMock()
    message.bot.send_document = AsyncMock()

    # Mock message methods
    message.answer = AsyncMock(return_value=MagicMock(message_id=2))
    message.reply = AsyncMock(return_value=MagicMock(message_id=2))
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()

    return message


@pytest.fixture
def mock_telegram_callback(mock_telegram_user, mock_telegram_message):
    """Create mock Telegram callback query object.

    Args:
        mock_telegram_user: Mock user fixture.
        mock_telegram_message: Mock message fixture.

    Returns:
        MagicMock: Mock aiogram CallbackQuery with common attributes.
    """
    from unittest.mock import AsyncMock
    from unittest.mock import MagicMock

    callback = MagicMock()
    callback.id = "callback_123"
    callback.from_user = mock_telegram_user
    callback.message = mock_telegram_message
    callback.data = "action:value"
    callback.chat_instance = "chat_instance_123"

    # Mock callback methods
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.message.delete = AsyncMock()

    return callback


@pytest.fixture
def mock_telegram_bot():
    """Create mock Telegram bot object.

    Returns:
        MagicMock: Mock aiogram Bot with common methods.
    """
    from unittest.mock import AsyncMock
    from unittest.mock import MagicMock

    bot = MagicMock()
    bot.id = 123456789
    bot.username = "test_bot"

    # Mock bot methods
    bot.get_me = AsyncMock(
        return_value=MagicMock(id=123456789, username="test_bot"))
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_photo = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_voice = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_chat_action = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.answer_pre_checkout_query = AsyncMock()
    bot.refund_star_payment = AsyncMock()
    bot.create_invoice_link = AsyncMock(return_value="https://t.me/invoice/xxx")

    return bot


# ============================================================================
# Phase 5.5: Claude Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_claude_message():
    """Create mock Claude API message response.

    Returns:
        MagicMock: Mock Anthropic Message with common attributes.
    """
    from unittest.mock import MagicMock

    message = MagicMock()
    message.id = "msg_123"
    message.type = "message"
    message.role = "assistant"
    message.content = [MagicMock(type="text", text="Hello! How can I help?")]
    message.model = "claude-sonnet-4-5-20250929"
    message.stop_reason = "end_turn"
    message.usage = MagicMock(input_tokens=100, output_tokens=50)

    return message


@pytest.fixture
def mock_claude_stream_events():
    """Create mock Claude streaming events generator.

    Returns:
        list: List of mock streaming events.
    """
    from unittest.mock import MagicMock

    events = [
        MagicMock(type="message_start",
                  message=MagicMock(id="msg_123",
                                    model="claude-sonnet-4-5-20250929")),
        MagicMock(type="content_block_start",
                  index=0,
                  content_block=MagicMock(type="text", text="")),
        MagicMock(type="content_block_delta",
                  index=0,
                  delta=MagicMock(type="text_delta", text="Hello")),
        MagicMock(type="content_block_delta",
                  index=0,
                  delta=MagicMock(type="text_delta", text=" world!")),
        MagicMock(type="content_block_stop", index=0),
        MagicMock(type="message_delta",
                  delta=MagicMock(stop_reason="end_turn"),
                  usage=MagicMock(output_tokens=10)),
        MagicMock(type="message_stop"),
    ]

    return events


@pytest.fixture
def mock_claude_tool_use_events():
    """Create mock Claude tool use streaming events.

    Returns:
        list: List of mock streaming events with tool use.
    """
    from unittest.mock import MagicMock

    events = [
        MagicMock(type="message_start",
                  message=MagicMock(id="msg_123",
                                    model="claude-sonnet-4-5-20250929")),
        MagicMock(type="content_block_start",
                  index=0,
                  content_block=MagicMock(type="tool_use",
                                          id="tool_123",
                                          name="web_search")),
        MagicMock(type="content_block_delta",
                  index=0,
                  delta=MagicMock(type="input_json_delta",
                                  partial_json='{"query": "test"}')),
        MagicMock(type="content_block_stop", index=0),
        MagicMock(type="message_delta",
                  delta=MagicMock(stop_reason="tool_use"),
                  usage=MagicMock(output_tokens=20)),
        MagicMock(type="message_stop"),
    ]

    return events


@pytest.fixture
def mock_claude_provider():
    """Create mock Claude provider.

    Returns:
        MagicMock: Mock ClaudeProvider with common methods.
    """
    from unittest.mock import AsyncMock
    from unittest.mock import MagicMock

    provider = MagicMock()
    provider.create_message = AsyncMock()
    provider.stream_message = AsyncMock()
    provider.stream_events = AsyncMock()
    provider.count_tokens = MagicMock(return_value=100)

    return provider


# ============================================================================
# Phase 5.5: Redis Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_redis():
    """Create mock Redis client.

    Returns:
        MagicMock: Mock Redis client with common methods.
    """
    from unittest.mock import AsyncMock
    from unittest.mock import MagicMock

    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.setex = AsyncMock(return_value=True)
    redis.expire = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=0)
    redis.incr = AsyncMock(return_value=1)
    redis.decr = AsyncMock(return_value=0)
    redis.lpush = AsyncMock(return_value=1)
    redis.rpush = AsyncMock(return_value=1)
    redis.lrange = AsyncMock(return_value=[])
    redis.hget = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=1)
    redis.hgetall = AsyncMock(return_value={})
    redis.pipeline = MagicMock()

    return redis
