"""Tests for UserRepository.

This module contains comprehensive tests for UserRepository operations,
including get_by_telegram_id, get_or_create, and other user-specific methods.

NO __init__.py - use direct import:
    pytest tests/test_user_repository.py
"""

from datetime import datetime
from datetime import timezone

from db.models.user import User
from db.repositories.user_repository import UserRepository
import pytest
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_get_by_telegram_id_existing(test_session, sample_user):
    """Test retrieving existing user by Telegram ID.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = UserRepository(test_session)

    user = await repo.get_by_telegram_id(sample_user.id)

    assert user is not None
    assert user.id == sample_user.id
    assert user.username == sample_user.username
    assert user.first_name == sample_user.first_name


@pytest.mark.asyncio
async def test_get_by_telegram_id_missing(test_session):
    """Test retrieving non-existent user returns None.

    Args:
        test_session: Async session fixture.
    """
    repo = UserRepository(test_session)

    user = await repo.get_by_telegram_id(999999999)

    assert user is None


@pytest.mark.asyncio
async def test_get_or_create_new_user(test_session):
    """Test creating new user via get_or_create.

    Verifies that new user is created with all fields set correctly
    and was_created flag is True.

    Args:
        test_session: Async session fixture.
    """
    repo = UserRepository(test_session)

    user, was_created = await repo.get_or_create(
        telegram_id=123456789,
        first_name='Test',
        last_name='User',
        username='test_user',
        language_code='en',
        is_premium=True,
        is_bot=False,
        added_to_attachment_menu=False,
    )

    assert was_created is True
    assert user.id == 123456789
    assert user.first_name == 'Test'
    assert user.last_name == 'User'
    assert user.username == 'test_user'
    assert user.language_code == 'en'
    assert user.is_premium is True
    assert user.is_bot is False
    assert user.added_to_attachment_menu is False
    assert user.first_seen_at is not None
    assert user.last_seen_at is not None


@pytest.mark.asyncio
async def test_get_or_create_existing_user(test_session, sample_user):
    """Test getting existing user via get_or_create.

    Verifies that existing user is returned (not created again)
    and last_seen_at is updated.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = UserRepository(test_session)
    original_last_seen = sample_user.last_seen_at

    # Small delay to ensure timestamp difference
    import asyncio
    await asyncio.sleep(0.01)

    user, was_created = await repo.get_or_create(
        telegram_id=sample_user.id,
        first_name='Updated Name',
        username='updated_username',
    )

    assert was_created is False
    assert user.id == sample_user.id
    assert user.last_seen_at > original_last_seen


@pytest.mark.asyncio
async def test_get_or_create_updates_profile(test_session, sample_user):
    """Test that get_or_create updates user profile fields.

    When user exists, get_or_create should update all profile fields
    with new values from Telegram.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = UserRepository(test_session)

    user, was_created = await repo.get_or_create(
        telegram_id=sample_user.id,
        first_name='Updated First',
        last_name='Updated Last',
        username='updated_username',
        language_code='ru',
        is_premium=True,
    )

    assert was_created is False
    assert user.first_name == 'Updated First'
    assert user.last_name == 'Updated Last'
    assert user.username == 'updated_username'
    assert user.language_code == 'ru'
    assert user.is_premium is True


@pytest.mark.asyncio
async def test_update_last_seen(test_session, sample_user):
    """Test updating user's last_seen_at timestamp.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = UserRepository(test_session)
    original_last_seen = sample_user.last_seen_at

    # Small delay to ensure timestamp difference
    import asyncio
    await asyncio.sleep(0.01)

    await repo.update_last_seen(sample_user.id)

    updated_user = await repo.get_by_telegram_id(sample_user.id)
    assert updated_user.last_seen_at > original_last_seen


@pytest.mark.asyncio
async def test_update_last_seen_missing(test_session):
    """Test updating last_seen for non-existent user raises ValueError.

    Args:
        test_session: Async session fixture.
    """
    repo = UserRepository(test_session)

    with pytest.raises(ValueError, match='User 999999999 not found'):
        await repo.update_last_seen(999999999)


@pytest.mark.asyncio
async def test_get_users_count(test_session, sample_user):
    """Test counting users in database.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = UserRepository(test_session)

    # Create additional user
    await repo.get_or_create(
        telegram_id=987654321,
        first_name='Second User',
    )

    count = await repo.get_users_count()

    assert count == 2  # sample_user + newly created


@pytest.mark.asyncio
async def test_get_users_count_empty(test_session):
    """Test counting users in empty database returns 0.

    Args:
        test_session: Async session fixture.
    """
    repo = UserRepository(test_session)

    count = await repo.get_users_count()

    assert count == 0


@pytest.mark.asyncio
async def test_username_uniqueness(test_session):
    """Test that duplicate usernames raise IntegrityError.

    Since username has unique constraint in schema,
    attempting to create two users with same username should fail.

    Args:
        test_session: Async session fixture.
    """
    from sqlalchemy.exc import IntegrityError

    repo = UserRepository(test_session)

    # Create first user with username
    await repo.get_or_create(
        telegram_id=111111111,
        first_name='User One',
        username='duplicate_username',
    )

    # Try to create second user with same username - should raise IntegrityError
    with pytest.raises(IntegrityError):
        await repo.get_or_create(
            telegram_id=222222222,
            first_name='User Two',
            username='duplicate_username',
        )


@pytest.mark.asyncio
async def test_premium_flag(test_session):
    """Test that is_premium field is stored and retrieved correctly.

    Args:
        test_session: Async session fixture.
    """
    repo = UserRepository(test_session)

    # Create premium user
    user_premium, _ = await repo.get_or_create(
        telegram_id=111111111,
        first_name='Premium User',
        is_premium=True,
    )

    # Create non-premium user
    user_regular, _ = await repo.get_or_create(
        telegram_id=222222222,
        first_name='Regular User',
        is_premium=False,
    )

    assert user_premium.is_premium is True
    assert user_regular.is_premium is False

    # Verify persistence
    retrieved_premium = await repo.get_by_telegram_id(111111111)
    retrieved_regular = await repo.get_by_telegram_id(222222222)

    assert retrieved_premium.is_premium is True
    assert retrieved_regular.is_premium is False
