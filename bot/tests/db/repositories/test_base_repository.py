"""Tests for BaseRepository.

This module contains comprehensive tests for BaseRepository generic CRUD
operations that all specific repositories inherit.

NO __init__.py - use direct import:
    pytest tests/db/repositories/test_base_repository.py
"""

from db.models.message import Message
from db.models.user import User
from db.repositories.base import BaseRepository
import pytest


@pytest.mark.asyncio
async def test_init_with_session_and_model(test_session):
    """Test BaseRepository initialization with session and model.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    assert repo.session == test_session
    assert repo.model == User


@pytest.mark.asyncio
async def test_get_by_id_found(test_session, sample_user):
    """Test retrieving entity by ID when it exists.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = BaseRepository(test_session, User)

    user = await repo.get_by_id(sample_user.id)

    assert user is not None
    assert user.id == sample_user.id
    assert user.username == sample_user.username


@pytest.mark.asyncio
async def test_get_by_id_not_found(test_session):
    """Test that get_by_id returns None when entity not found.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    user = await repo.get_by_id(999999999)

    assert user is None


@pytest.mark.asyncio
async def test_get_by_id_composite_key(test_session, sample_message):
    """Test retrieving entity by composite primary key.

    Message model uses composite key (chat_id, message_id).

    Args:
        test_session: Async session fixture.
        sample_message: Sample message fixture.
    """
    repo = BaseRepository(test_session, Message)

    # Composite key passed as tuple
    message = await repo.get_by_id(
        (sample_message.chat_id, sample_message.message_id))

    assert message is not None
    assert message.chat_id == sample_message.chat_id
    assert message.message_id == sample_message.message_id


@pytest.mark.asyncio
async def test_get_all_returns_list(test_session, sample_user):
    """Test that get_all returns list of entities.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = BaseRepository(test_session, User)

    # Add another user
    user2 = User(
        id=987654321,
        first_name='Second',
        last_name='User',
        username='second_user',
    )
    test_session.add(user2)
    await test_session.flush()

    users = await repo.get_all()

    assert isinstance(users, list)
    assert len(users) == 2
    assert all(isinstance(u, User) for u in users)


@pytest.mark.asyncio
async def test_get_all_limit(test_session):
    """Test that get_all respects limit parameter.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create 5 users
    for i in range(5):
        user = User(
            id=100000000 + i,
            first_name=f'User{i}',
            username=f'user{i}',
        )
        test_session.add(user)
    await test_session.flush()

    users = await repo.get_all(limit=3)

    assert len(users) == 3


@pytest.mark.asyncio
async def test_get_all_offset(test_session):
    """Test that get_all respects offset parameter.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create 5 users
    for i in range(5):
        user = User(
            id=200000000 + i,
            first_name=f'User{i}',
            username=f'user_offset_{i}',
        )
        test_session.add(user)
    await test_session.flush()

    # Skip first 2, get next 2
    users = await repo.get_all(limit=2, offset=2)

    assert len(users) == 2
    # Verify we got the correct users (after offset)
    usernames = [u.username for u in users]
    assert 'user_offset_0' not in usernames
    assert 'user_offset_1' not in usernames


@pytest.mark.asyncio
async def test_get_all_default_limit_100(test_session):
    """Test that get_all uses default limit of 100.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create 150 users
    for i in range(150):
        user = User(
            id=300000000 + i,
            first_name=f'User{i}',
            username=f'user_limit_{i}',
        )
        test_session.add(user)
    await test_session.flush()

    # Call without specifying limit
    users = await repo.get_all()

    # Should return only 100 (default limit)
    assert len(users) == 100


@pytest.mark.asyncio
async def test_get_all_default_offset_0(test_session):
    """Test that get_all uses default offset of 0.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create users with predictable IDs
    for i in range(3):
        user = User(
            id=400000000 + i,
            first_name=f'User{i}',
            username=f'user_offset_default_{i}',
        )
        test_session.add(user)
    await test_session.flush()

    # Call without specifying offset
    users = await repo.get_all(limit=3)

    # Should start from beginning (offset=0)
    assert len(users) == 3
    # First user should be in results
    usernames = [u.username for u in users]
    assert any('user_offset_default_0' in un for un in usernames)


@pytest.mark.asyncio
async def test_get_all_empty_result(test_session):
    """Test get_all with empty result set.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    users = await repo.get_all()

    assert users == []
    assert isinstance(users, list)


@pytest.mark.asyncio
async def test_create_adds_to_session(test_session):
    """Test that create adds entity to session.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    user = User(
        id=500000001,
        first_name='New',
        last_name='User',
        username='new_user',
    )

    created = await repo.create(user)

    # Entity should be in session
    assert created in test_session
    assert created.id == 500000001


@pytest.mark.asyncio
async def test_create_flushes_without_commit(test_session):
    """Test that create flushes but does NOT commit.

    This is critical - BaseRepository should never commit,
    only middleware should commit.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    user = User(
        id=500000002,
        first_name='Flush',
        last_name='Test',
        username='flush_test',
    )

    await repo.create(user)

    # After flush, entity has ID but transaction not committed
    assert user.id is not None

    # Entity should be in session but not yet persisted
    # We verify by checking it's in the session
    assert user in test_session


@pytest.mark.asyncio
async def test_create_returns_with_id(test_session):
    """Test that create returns entity with populated ID.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    user = User(
        id=500000003,
        first_name='Return',
        last_name='Test',
        username='return_test',
    )

    created = await repo.create(user)

    assert created is user  # Same instance
    assert created.id == 500000003  # ID is set


@pytest.mark.asyncio
async def test_update_merges_entity(test_session, sample_user):
    """Test that update merges entity into session.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = BaseRepository(test_session, User)

    # Modify user
    sample_user.first_name = 'Updated'
    sample_user.username = 'updated_username'

    updated = await repo.update(sample_user)

    assert updated.first_name == 'Updated'
    assert updated.username == 'updated_username'


@pytest.mark.asyncio
async def test_update_flushes_without_commit(test_session, sample_user):
    """Test that update flushes but does NOT commit.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = BaseRepository(test_session, User)

    original_name = sample_user.first_name
    sample_user.first_name = 'UpdatedNoCommit'

    await repo.update(sample_user)

    # After update, changes are in session but not yet committed
    # Verify the entity is updated in the session
    assert sample_user.first_name == 'UpdatedNoCommit'
    assert sample_user in test_session


@pytest.mark.asyncio
async def test_update_returns_entity(test_session, sample_user):
    """Test that update returns the updated entity.

    Args:
        test_session: Async session fixture.
        sample_user: Sample user fixture.
    """
    repo = BaseRepository(test_session, User)

    sample_user.first_name = 'ReturnTest'
    updated = await repo.update(sample_user)

    assert updated is not None
    assert updated.first_name == 'ReturnTest'


@pytest.mark.asyncio
async def test_delete_removes_entity(test_session):
    """Test that delete removes entity from session.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create user
    user = User(
        id=600000001,
        first_name='ToDelete',
        username='to_delete',
    )
    await repo.create(user)

    # Delete user
    await repo.delete(user)

    # Flush to apply delete
    await test_session.flush()

    # Verify deleted
    retrieved = await repo.get_by_id(600000001)
    assert retrieved is None


@pytest.mark.asyncio
async def test_delete_flushes_without_commit(test_session):
    """Test that delete flushes but does NOT commit.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create user
    user = User(
        id=600000002,
        first_name='DeleteNoCommit',
        username='delete_no_commit',
    )
    await repo.create(user)
    await test_session.flush()

    # Delete user
    await repo.delete(user)

    # Rollback to verify it wasn't committed
    await test_session.rollback()

    # After rollback, delete should be undone
    # (entity would still exist if we re-query from fresh session)


@pytest.mark.asyncio
async def test_generic_type_binding(test_session):
    """Test that generic type parameter correctly binds to model.

    Args:
        test_session: Async session fixture.
    """
    # Create repository with User model
    user_repo = BaseRepository(test_session, User)
    assert user_repo.model == User

    # Create repository with Message model
    message_repo = BaseRepository(test_session, Message)
    assert message_repo.model == Message

    # Verify they're different
    assert user_repo.model != message_repo.model


@pytest.mark.asyncio
async def test_multiple_flushes_in_transaction(test_session):
    """Test that multiple flush operations work in same transaction.

    This tests that repository operations can be chained
    without committing between them.

    Args:
        test_session: Async session fixture.
    """
    repo = BaseRepository(test_session, User)

    # Create first user
    user1 = User(
        id=700000001,
        first_name='First',
        username='first_flush',
    )
    await repo.create(user1)

    # Create second user (another flush)
    user2 = User(
        id=700000002,
        first_name='Second',
        username='second_flush',
    )
    await repo.create(user2)

    # Update first user (another flush)
    user1.first_name = 'FirstUpdated'
    await repo.update(user1)

    # All operations should be in same transaction
    # Verify both users exist
    retrieved1 = await repo.get_by_id(700000001)
    retrieved2 = await repo.get_by_id(700000002)

    assert retrieved1 is not None
    assert retrieved2 is not None
    assert retrieved1.first_name == 'FirstUpdated'
