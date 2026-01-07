"""Tests for ChatRepository.

This module contains comprehensive tests for ChatRepository operations,
including get_by_telegram_id, get_or_create, and chat type-specific methods.

NO __init__.py - use direct import:
    pytest tests/test_chat_repository.py
"""

from db.models.chat import Chat
from db.repositories.chat_repository import ChatRepository
import pytest


@pytest.mark.asyncio
async def test_get_by_telegram_id(test_session, sample_chat):
    """Test retrieving chat by Telegram ID.

    Args:
        test_session: Async session fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ChatRepository(test_session)

    chat = await repo.get_by_telegram_id(sample_chat.id)

    assert chat is not None
    assert chat.id == sample_chat.id
    assert chat.type == sample_chat.type
    assert chat.username == sample_chat.username


@pytest.mark.asyncio
async def test_get_or_create_private_chat(test_session):
    """Test creating private chat via get_or_create.

    Private chats have first_name/last_name instead of title.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    chat, was_created = await repo.get_or_create(
        telegram_id=111111111,
        chat_type='private',
        first_name='John',
        last_name='Doe',
        username='john_doe',
    )

    assert was_created is True
    assert chat.type == 'private'
    assert chat.first_name == 'John'
    assert chat.last_name == 'Doe'
    assert chat.username == 'john_doe'
    assert chat.title is None
    assert chat.is_forum is False


@pytest.mark.asyncio
async def test_get_or_create_group_chat(test_session):
    """Test creating group chat via get_or_create.

    Groups have title but not first_name/last_name.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    chat, was_created = await repo.get_or_create(
        telegram_id=222222222,
        chat_type='group',
        title='Test Group',
        username='test_group',
    )

    assert was_created is True
    assert chat.type == 'group'
    assert chat.title == 'Test Group'
    assert chat.username == 'test_group'
    assert chat.first_name is None
    assert chat.last_name is None
    assert chat.is_forum is False


@pytest.mark.asyncio
async def test_get_or_create_supergroup(test_session):
    """Test creating supergroup via get_or_create.

    Supergroups are like groups but with more features.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    chat, was_created = await repo.get_or_create(
        telegram_id=333333333,
        chat_type='supergroup',
        title='Test Supergroup',
        username='test_supergroup',
        is_forum=False,
    )

    assert was_created is True
    assert chat.type == 'supergroup'
    assert chat.title == 'Test Supergroup'
    assert chat.username == 'test_supergroup'
    assert chat.is_forum is False


@pytest.mark.asyncio
async def test_get_or_create_channel(test_session):
    """Test creating channel via get_or_create.

    Channels are for broadcasting messages.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    chat, was_created = await repo.get_or_create(
        telegram_id=444444444,
        chat_type='channel',
        title='Test Channel',
        username='test_channel',
    )

    assert was_created is True
    assert chat.type == 'channel'
    assert chat.title == 'Test Channel'
    assert chat.username == 'test_channel'
    assert chat.is_forum is False


@pytest.mark.asyncio
async def test_get_or_create_forum_supergroup(test_session):
    """Test creating forum supergroup (with topics enabled).

    Forum supergroups support topics/threads (Bot API 9.3).

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    chat, was_created = await repo.get_or_create(
        telegram_id=555555555,
        chat_type='supergroup',
        title='Forum Supergroup',
        is_forum=True,
    )

    assert was_created is True
    assert chat.type == 'supergroup'
    assert chat.title == 'Forum Supergroup'
    assert chat.is_forum is True


@pytest.mark.asyncio
async def test_get_or_create_updates_chat(test_session, sample_chat):
    """Test that get_or_create updates existing chat info.

    When chat exists, get_or_create should update all fields.

    Args:
        test_session: Async session fixture.
        sample_chat: Sample chat fixture.
    """
    repo = ChatRepository(test_session)

    chat, was_created = await repo.get_or_create(
        telegram_id=sample_chat.id,
        chat_type='private',
        first_name='Updated First',
        last_name='Updated Last',
        username='updated_username',
    )

    assert was_created is False
    assert chat.id == sample_chat.id
    assert chat.first_name == 'Updated First'
    assert chat.last_name == 'Updated Last'
    assert chat.username == 'updated_username'


@pytest.mark.asyncio
async def test_get_by_username(test_session):
    """Test finding chat by username.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    # Create chat with username
    await repo.get_or_create(
        telegram_id=666666666,
        chat_type='supergroup',
        title='Public Group',
        username='public_group',
    )

    chat = await repo.get_by_username('public_group')

    assert chat is not None
    assert chat.username == 'public_group'
    assert chat.title == 'Public Group'

    # Test non-existent username
    chat_missing = await repo.get_by_username('nonexistent')
    assert chat_missing is None


@pytest.mark.asyncio
async def test_get_by_type(test_session):
    """Test filtering chats by type.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    # Create chats of different types
    await repo.get_or_create(
        telegram_id=111111111,
        chat_type='private',
        first_name='User 1',
    )
    await repo.get_or_create(
        telegram_id=222222222,
        chat_type='private',
        first_name='User 2',
    )
    await repo.get_or_create(
        telegram_id=333333333,
        chat_type='group',
        title='Group 1',
    )

    # Get only private chats
    private_chats = await repo.get_by_type('private')
    assert len(private_chats) == 2
    assert all(chat.type == 'private' for chat in private_chats)

    # Get only groups
    group_chats = await repo.get_by_type('group')
    assert len(group_chats) == 1
    assert group_chats[0].type == 'group'


@pytest.mark.asyncio
async def test_get_forum_chats(test_session):
    """Test getting only forum-enabled chats.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    # Create regular supergroup
    await repo.get_or_create(
        telegram_id=111111111,
        chat_type='supergroup',
        title='Regular Supergroup',
        is_forum=False,
    )

    # Create forum supergroups
    await repo.get_or_create(
        telegram_id=222222222,
        chat_type='supergroup',
        title='Forum 1',
        is_forum=True,
    )
    await repo.get_or_create(
        telegram_id=333333333,
        chat_type='supergroup',
        title='Forum 2',
        is_forum=True,
    )

    forum_chats = await repo.get_forum_chats()

    assert len(forum_chats) == 2
    assert all(chat.is_forum is True for chat in forum_chats)
    assert all(chat.type == 'supergroup'
               for chat in forum_chats)  # Forums are supergroups


@pytest.mark.asyncio
async def test_chat_type_validation(test_session):
    """Test that all 4 chat types work correctly.

    Verifies that private, group, supergroup, and channel types
    are all handled properly.

    Args:
        test_session: Async session fixture.
    """
    repo = ChatRepository(test_session)

    # Create all 4 types
    types_to_test = ['private', 'group', 'supergroup', 'channel']

    for i, chat_type in enumerate(types_to_test):
        chat, was_created = await repo.get_or_create(
            telegram_id=100000000 + i,
            chat_type=chat_type,
            title=f'Test {chat_type}' if chat_type != 'private' else None,
            first_name='Test' if chat_type == 'private' else None,
        )

        assert was_created is True
        assert chat.type == chat_type

    # Verify all were created
    for i, chat_type in enumerate(types_to_test):
        chat = await repo.get_by_telegram_id(100000000 + i)
        assert chat is not None
        assert chat.type == chat_type
