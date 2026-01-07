"""Database integration tests.

This module contains end-to-end integration tests for the database layer,
testing the complete workflow from User creation through Message storage.

NO __init__.py - use direct import:
    pytest tests/db/test_integration_db.py
"""

from db.models.message import MessageRole
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
import pytest


@pytest.mark.asyncio
async def test_full_message_workflow(test_session):
    """Test complete database workflow: User → Chat → Thread → Message.

    This integration test verifies that all repositories work together
    correctly and that relationships between entities are properly
    maintained.

    Workflow:
    1. Create user (telegram user who sends message)
    2. Create chat (where conversation happens)
    3. Create thread (conversation context)
    4. Create multiple messages (conversation history)
    5. Query conversation history
    6. Verify all relationships and data integrity

    Args:
        test_session: Async session fixture.
    """
    # Step 1: Create User
    user_repo = UserRepository(test_session)
    user, was_created = await user_repo.get_or_create(
        telegram_id=123456789,
        first_name='Test',
        last_name='User',
        username='test_user',
        language_code='en',
        is_premium=False,
    )

    assert was_created is True
    assert user.id == 123456789
    assert user.username == 'test_user'

    # Step 2: Create Chat
    chat_repo = ChatRepository(test_session)
    chat, was_created = await chat_repo.get_or_create(
        telegram_id=987654321,
        chat_type='private',
        first_name='Test',
        last_name='User',
        username='test_user',
    )

    assert was_created is True
    assert chat.id == 987654321
    assert chat.type == 'private'

    # Step 3: Create Thread
    thread_repo = ThreadRepository(test_session)
    thread, was_created = await thread_repo.get_or_create_thread(
        chat_id=chat.id,
        user_id=user.id,
        thread_id=None,  # Main chat (not forum topic)
        model_name='claude-3-5-sonnet-20241022',
        system_prompt='You are a helpful assistant.',
    )

    assert was_created is True
    assert thread.chat_id == chat.id
    assert thread.user_id == user.id
    assert thread.thread_id is None
    assert thread.model_name == 'claude-3-5-sonnet-20241022'

    # Step 4: Create conversation history
    msg_repo = MessageRepository(test_session)

    # User's first message
    msg1 = await msg_repo.create_message(
        chat_id=chat.id,
        message_id=1001,
        thread_id=thread.id,
        from_user_id=user.id,
        date=1234567890,
        role=MessageRole.USER,
        text_content='Hello! Can you help me with Python?',
    )

    assert msg1.chat_id == chat.id
    assert msg1.message_id == 1001
    assert msg1.thread_id == thread.id
    assert msg1.role == MessageRole.USER

    # Assistant's response
    msg2 = await msg_repo.create_message(
        chat_id=chat.id,
        message_id=1002,
        thread_id=thread.id,
        from_user_id=None,  # Bot message
        date=1234567891,
        role=MessageRole.ASSISTANT,
        text_content='Of course! I would be happy to help you with Python.',
    )

    assert msg2.role == MessageRole.ASSISTANT
    assert msg2.from_user_id is None  # Bot has no user_id

    # User's follow-up with attachment
    msg3 = await msg_repo.create_message(
        chat_id=chat.id,
        message_id=1003,
        thread_id=thread.id,
        from_user_id=user.id,
        date=1234567892,
        role=MessageRole.USER,
        text_content='Here is my code',
        attachments=[{
            'type': 'document',
            'file_id': 'BQACAgIAAxkBAAI...',
            'file_name': 'script.py',
            'mime_type': 'text/x-python',
            'file_size': 2048,
        }],
    )

    assert msg3.has_documents is True
    assert msg3.attachment_count == 1
    assert msg3.attachments[0]['file_name'] == 'script.py'

    # Assistant's response with token tracking
    msg4 = await msg_repo.create_message(
        chat_id=chat.id,
        message_id=1004,
        thread_id=thread.id,
        from_user_id=None,
        date=1234567893,
        role=MessageRole.ASSISTANT,
        text_content='I see the issue. You need to...',
    )

    # Track LLM token usage
    await msg_repo.add_tokens(
        chat_id=chat.id,
        message_id=1004,
        input_tokens=150,
        output_tokens=75,
    )

    # Step 5: Query conversation history
    history = await msg_repo.get_thread_messages(thread.id)

    assert len(history) == 4
    # Verify order (ASC by date for LLM context)
    assert history[0].text_content == 'Hello! Can you help me with Python?'
    assert history[1].role == MessageRole.ASSISTANT
    assert history[2].has_documents is True
    assert history[3].input_tokens == 150
    assert history[3].output_tokens == 75

    # Verify messages are ordered correctly
    assert history[0].date < history[1].date < history[2].date < history[3].date

    # Step 6: Verify relationships
    # Get user's threads
    user_threads = await thread_repo.get_user_threads(user.id)
    assert len(user_threads) == 1
    assert user_threads[0].id == thread.id

    # Get chat's threads
    chat_threads = await thread_repo.get_chat_threads(chat.id)
    assert len(chat_threads) == 1
    assert chat_threads[0].id == thread.id

    # Get recent messages in chat
    recent = await msg_repo.get_recent_messages(chat.id, limit=10)
    assert len(recent) == 4
    # Recent messages ordered DESC (newest first)
    assert recent[0].message_id == 1004
    assert recent[3].message_id == 1001

    # Get messages with attachments only
    with_attachments = await msg_repo.get_messages_with_attachments(thread.id)
    assert len(with_attachments) == 1
    assert with_attachments[0].message_id == 1003

    # Step 7: Test updating existing entities
    # Update user profile
    user2, was_created = await user_repo.get_or_create(
        telegram_id=123456789,  # Same user
        first_name='Updated',
        username='updated_user',
        is_premium=True,  # Upgraded to premium
    )

    assert was_created is False  # Existing user
    assert user2.first_name == 'Updated'
    assert user2.is_premium is True

    # Update message (edit)
    await msg_repo.update_message(
        chat_id=chat.id,
        message_id=1001,
        text_content='Hello! Can you help me with Python? (edited)',
        edit_date=1234567899,
    )

    updated_msg = await msg_repo.get_message(chat.id, 1001)
    assert '(edited)' in updated_msg.text_content
    assert updated_msg.edit_date == 1234567899

    # Step 8: Test pagination
    # Create more messages for pagination test
    for i in range(10):
        await msg_repo.create_message(
            chat_id=chat.id,
            message_id=2000 + i,
            thread_id=thread.id,
            from_user_id=user.id,
            date=1234568000 + i,
            role=MessageRole.USER,
            text_content=f'Pagination test message {i}',
        )

    # Get with limit
    limited = await msg_repo.get_thread_messages(thread.id, limit=5)
    assert len(limited) == 5

    # Get with offset
    offset_messages = await msg_repo.get_thread_messages(
        thread.id,
        limit=5,
        offset=5,
    )
    assert len(offset_messages) == 5
    assert offset_messages[0].text_content != limited[0].text_content

    # Step 9: Test users count
    # Create another user
    await user_repo.get_or_create(
        telegram_id=111111111,
        first_name='Second',
        username='second_user',
    )

    user_count = await user_repo.get_users_count()
    assert user_count == 2

    # Step 10: Test forum thread (separate conversation)
    # Create forum thread in same chat
    forum_thread, was_created = await thread_repo.get_or_create_thread(
        chat_id=chat.id,
        user_id=user.id,
        thread_id=12345,  # Forum topic ID
        title='Python Help',
        model_name='claude-3-5-sonnet-20241022',
    )

    assert was_created is True
    assert forum_thread.thread_id == 12345
    assert forum_thread.title == 'Python Help'
    assert forum_thread.id != thread.id  # Different thread

    # Verify user now has 2 threads
    user_threads_updated = await thread_repo.get_user_threads(user.id)
    assert len(user_threads_updated) == 2

    # Messages in different threads don't interfere
    await msg_repo.create_message(
        chat_id=chat.id,
        message_id=3001,
        thread_id=forum_thread.id,
        from_user_id=user.id,
        date=1234569000,
        role=MessageRole.USER,
        text_content='Forum topic message',
    )

    main_thread_messages = await msg_repo.get_thread_messages(thread.id)
    forum_thread_messages = await msg_repo.get_thread_messages(forum_thread.id)

    assert len(main_thread_messages) == 14  # 4 original + 10 pagination
    assert len(forum_thread_messages) == 1
    assert forum_thread_messages[0].text_content == 'Forum topic message'

    # Final verification: All data is consistent
    assert user.id == user2.id  # Same user object
    assert thread.chat_id == chat.id
    assert thread.user_id == user.id
    assert all(msg.chat_id == chat.id for msg in history)
    assert all(msg.thread_id == thread.id for msg in history)

    print('✅ Full integration test passed successfully!')
    print(f'  Created: {user_count} users, 1 chat, 2 threads, 15 messages')
    print(f'  Verified: relationships, pagination, updates, forum threads')
