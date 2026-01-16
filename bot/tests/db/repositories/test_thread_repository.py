"""Tests for ThreadRepository.

This module contains comprehensive tests for ThreadRepository operations,
including thread creation, unique constraints, and forum topic support.

NO __init__.py - use direct import:
    pytest tests/test_thread_repository.py
"""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import patch

from db.repositories.thread_repository import ThreadRepository
import pytest
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_get_or_create_thread_main_chat(
    test_session,
    sample_user,
    sample_chat,
):
    """Test creating thread for main chat (thread_id=None).

    Main chat threads have thread_id=None (not a forum topic).

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ThreadRepository(test_session)

    thread, was_created = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,  # Main chat
    )

    assert was_created is True
    assert thread.chat_id == sample_chat.id
    assert thread.user_id == sample_user.id
    assert thread.thread_id is None
    # Phase 1.4.2: model_id moved to User, system_prompt removed


@pytest.mark.asyncio
async def test_get_or_create_thread_forum_topic(
    test_session,
    sample_user,
    sample_chat,
):
    """Test creating thread for forum topic (thread_id=123).

    Forum topics have specific thread_id from Telegram Bot API 9.3.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ThreadRepository(test_session)

    thread, was_created = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=12345,  # Forum topic ID
        title='General Discussion',
    )

    assert was_created is True
    assert thread.chat_id == sample_chat.id
    assert thread.user_id == sample_user.id
    assert thread.thread_id == 12345
    assert thread.title == 'General Discussion'


@pytest.mark.asyncio
async def test_get_or_create_thread_unique_constraint(
    test_session,
    sample_user,
    sample_chat,
):
    """Test that only one thread per user per topic is allowed.

    The unique constraint ensures one thread per (chat_id, user_id,
    COALESCE(thread_id, 0)).

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ThreadRepository(test_session)

    # Create first thread
    thread1, was_created1 = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,  # Main chat
    )

    # Try to create duplicate
    thread2, was_created2 = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,  # Same thread
    )

    assert was_created1 is True
    assert was_created2 is False
    assert thread1.id == thread2.id  # Same thread returned


@pytest.mark.asyncio
async def test_get_active_thread(
    test_session,
    sample_thread,
):
    """Test finding existing active thread.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
    """
    repo = ThreadRepository(test_session)

    thread = await repo.get_active_thread(
        chat_id=sample_thread.chat_id,
        user_id=sample_thread.user_id,
        thread_id=sample_thread.thread_id,
    )

    assert thread is not None
    assert thread.id == sample_thread.id
    assert thread.chat_id == sample_thread.chat_id
    assert thread.user_id == sample_thread.user_id


@pytest.mark.asyncio
async def test_get_active_thread_missing(test_session):
    """Test that get_active_thread returns None if not found.

    Args:
        test_session: Async session fixture.
    """
    repo = ThreadRepository(test_session)

    thread = await repo.get_active_thread(
        chat_id=999999999,
        user_id=888888888,
        thread_id=None,
    )

    assert thread is None


@pytest.mark.asyncio
async def test_get_user_threads(
    test_session,
    sample_user,
    sample_chat,
):
    """Test getting all threads for a user.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ThreadRepository(test_session)

    # Create multiple threads for same user
    await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,  # Main chat
    )
    await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=123,  # Forum topic 1
    )
    await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=456,  # Forum topic 2
    )

    threads = await repo.get_user_threads(sample_user.id)

    assert len(threads) == 3
    assert all(thread.user_id == sample_user.id for thread in threads)


@pytest.mark.asyncio
async def test_get_chat_threads(
    test_session,
    sample_chat,
):
    """Test getting all threads in a chat.

    Args:
        test_session: Async session fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ThreadRepository(test_session)

    # Create threads from different users in same chat
    await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=111111111,
        thread_id=None,
    )
    await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=222222222,
        thread_id=None,
    )

    threads = await repo.get_chat_threads(sample_chat.id)

    assert len(threads) == 2
    assert all(thread.chat_id == sample_chat.id for thread in threads)


# Phase 1.4.2: update_thread_model() removed - model_id now in User, not Thread


@pytest.mark.asyncio
async def test_delete_thread(test_session, sample_thread):
    """Test deleting thread.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
    """
    repo = ThreadRepository(test_session)

    await repo.delete_thread(sample_thread.id)

    # Verify thread was deleted
    deleted_thread = await repo.get_by_id(sample_thread.id)
    assert deleted_thread is None


@pytest.mark.asyncio
async def test_thread_coalesce_logic(
    test_session,
    sample_user,
    sample_chat,
):
    """Test NULL vs 0 handling in thread_id unique constraint.

    The COALESCE(thread_id, 0) logic ensures:
    - thread_id=NULL is treated as 0
    - thread_id=0 would also be treated as 0
    - Different thread_id values are kept separate

    This test verifies that main chat (NULL) and different forum topics
    create separate threads.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ThreadRepository(test_session)

    # Create thread for main chat (thread_id=None)
    main_thread, _ = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,
    )

    # Create thread for forum topic (thread_id=123)
    topic_thread, _ = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=123,
    )

    # Verify they are different threads
    assert main_thread.id != topic_thread.id
    assert main_thread.thread_id is None
    assert topic_thread.thread_id == 123

    # Verify we can find them separately
    found_main = await repo.get_active_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=None,
    )
    found_topic = await repo.get_active_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=123,
    )

    assert found_main.id == main_thread.id
    assert found_topic.id == topic_thread.id


@pytest.mark.asyncio
async def test_get_or_create_thread_handles_race_condition(
    test_session,
    sample_user,
    sample_chat,
):
    """Test that concurrent thread creation handles IntegrityError gracefully.

    Regression test for bug: when multiple photos are sent simultaneously,
    parallel handlers all try to create the same thread. The first one
    succeeds, but the others hit UniqueViolationError.

    The fix: use savepoint (begin_nested) so IntegrityError doesn't
    invalidate the entire transaction, then fetch the existing thread.

    Bug scenario:
    1. User sends 5 photos at once
    2. 5 handlers run in parallel
    3. All see thread doesn't exist
    4. All try to INSERT
    5. First succeeds, 4 fail with UniqueViolationError
    6. Error shown to user: "failed to upload photo"

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    from db.models.thread import Thread

    repo = ThreadRepository(test_session)

    # First, create the thread directly in DB (simulating another handler)
    existing_thread = Thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=88888,
    )
    test_session.add(existing_thread)
    await test_session.flush()
    existing_thread_id = existing_thread.id

    # Now simulate race condition: get_active_thread returns None (cache miss)
    # but INSERT fails because thread already exists
    original_get_active_thread = repo.get_active_thread
    first_call = True

    async def mock_get_active_thread_first_miss(chat_id, user_id, thread_id):
        nonlocal first_call
        if first_call and thread_id == 88888:
            first_call = False
            return None  # Simulate cache miss / race condition
        return await original_get_active_thread(chat_id, user_id, thread_id)

    with patch.object(repo,
                      'get_active_thread',
                      side_effect=mock_get_active_thread_first_miss):
        # This should:
        # 1. Call get_active_thread -> returns None (mocked)
        # 2. Try to INSERT -> IntegrityError (thread exists)
        # 3. Catch error, call get_active_thread again -> returns thread
        # 4. Return existing thread with was_created=False
        thread, was_created = await repo.get_or_create_thread(
            chat_id=sample_chat.id,
            user_id=sample_user.id,
            thread_id=88888,
        )

    # Should return existing thread, not create new one
    assert was_created is False
    assert thread.id == existing_thread_id


@pytest.mark.asyncio
async def test_get_or_create_thread_uses_savepoint(
    test_session,
    sample_user,
    sample_chat,
):
    """Test that IntegrityError handling uses savepoint correctly.

    Verifies that after handling IntegrityError, the session is still
    usable for other operations (transaction not invalidated).

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    from db.models.thread import Thread

    repo = ThreadRepository(test_session)

    # Create thread directly
    existing_thread = Thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=77777,
    )
    test_session.add(existing_thread)
    await test_session.flush()

    # Mock to force IntegrityError path
    original_get_active_thread = repo.get_active_thread
    first_call = True

    async def mock_first_miss(chat_id, user_id, thread_id):
        nonlocal first_call
        if first_call and thread_id == 77777:
            first_call = False
            return None
        return await original_get_active_thread(chat_id, user_id, thread_id)

    with patch.object(repo, 'get_active_thread', side_effect=mock_first_miss):
        thread, _ = await repo.get_or_create_thread(
            chat_id=sample_chat.id,
            user_id=sample_user.id,
            thread_id=77777,
        )

    # After IntegrityError handling, session should still work
    # Try creating a different thread to verify transaction is valid
    new_thread, was_created = await repo.get_or_create_thread(
        chat_id=sample_chat.id,
        user_id=sample_user.id,
        thread_id=66666,  # Different thread_id
    )

    assert was_created is True
    assert new_thread.thread_id == 66666
